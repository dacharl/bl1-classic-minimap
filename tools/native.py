"""Light native helper for the BL1 executables (no symbols).
  natives  <exe> <regex>        resolve UnrealScript native exec thunks by name
  dis      <exe> <va> [maxins]  linear disassembly with string/call annotation
  strref   <exe> <text>         find code that references a string (LEA/PUSH imm)
"""
import sys, re, struct, mmap
import pefile, capstone

class Img:
    def __init__(self, path):
        self.pe = pe = pefile.PE(path, fast_load=True)
        self.x64 = pe.FILE_HEADER.Machine == 0x8664
        self.base = pe.OPTIONAL_HEADER.ImageBase
        self.secs = [(s.Name.rstrip(b'\0').decode(), self.base + s.VirtualAddress, s.Misc_VirtualSize,
                      s.PointerToRawData, s.SizeOfRawData, s.Characteristics) for s in pe.sections]
        self.data = open(path, 'rb').read()
        self.ptr = 8 if self.x64 else 4
        self.md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64 if self.x64 else capstone.CS_MODE_32)
        self.md.detail = True

    def off(self, va):
        for n, v, vs, ro, rs, ch in self.secs:
            if v <= va < v + max(vs, rs):
                o = va - v
                return ro + o if o < rs else None
        return None

    def va(self, off):
        for n, v, vs, ro, rs, ch in self.secs:
            if ro <= off < ro + rs:
                return v + off - ro
        return None

    def read(self, va, n):
        o = self.off(va); return self.data[o:o + n] if o is not None else b''

    def is_code(self, va):
        for n, v, vs, ro, rs, ch in self.secs:
            if v <= va < v + vs: return bool(ch & 0x20000000)
        return False

    def string_at(self, va):
        b = self.read(va, 256)
        if len(b) > 4 and b[1] == 0 and 32 <= b[0] < 127:
            s = b.decode('utf-16le', 'ignore').split('\0')[0]
            if len(s) >= 3: return 'L"%s"' % s
        s = b.split(b'\0')[0]
        if len(s) >= 3 and all(32 <= c < 127 or c in (9, 10) for c in s):
            return '"%s"' % s.decode()
        return None

    def find_all(self, needle):
        out = []; i = self.data.find(needle)
        while i >= 0:
            out.append(i); i = self.data.find(needle, i + 1)
        return out

    def ptr_refs(self, target_va):
        pat = struct.pack('<Q' if self.x64 else '<I', target_va)
        return [self.va(o) for o in self.find_all(pat)]

    def natives(self, rx):
        rx = re.compile(rx)
        res = []
        for m in re.finditer(rb'[A-Za-z_]\w*exec\w+\x00', self.data):
            name = m.group()[:-1].decode()
            if rx.search(name):
                for ref in self.ptr_refs(self.va(m.start())):
                    fn = struct.unpack('<Q' if self.x64 else '<I', self.read(ref + self.ptr, self.ptr))[0]
                    if self.is_code(fn): res.append((name, ref, fn))
        for m in re.finditer(rb'(?:[A-Za-z_]\x00)(?:\w\x00)*?e\x00x\x00e\x00c\x00(?:\w\x00)+\x00\x00', self.data):
            name = m.group().decode('utf-16le').rstrip('\0')
            if rx.search(name):
                for ref in self.ptr_refs(self.va(m.start())):
                    fn = struct.unpack('<Q' if self.x64 else '<I', self.read(ref + self.ptr, self.ptr))[0]
                    if self.is_code(fn): res.append((name, ref, fn))
        return res

    def dis(self, va, maxins=400, stop_at_ret=True):
        code = self.read(va, maxins * 15)
        lines = []
        for ins in self.md.disasm(code, va):
            ann = ''
            for op in ins.operands:
                tgt = None
                if op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_RIP:
                    tgt = ins.address + ins.size + op.mem.disp
                elif op.type == capstone.x86.X86_OP_IMM and op.imm > self.base:
                    tgt = op.imm
                elif op.type == capstone.x86.X86_OP_MEM and op.mem.base == 0 and op.mem.disp > self.base:
                    tgt = op.mem.disp
                if tgt:
                    s = self.string_at(tgt)
                    if s: ann += '  ; ' + s
            lines.append('%x: %-8s %s%s' % (ins.address, ins.mnemonic, ins.op_str, ann))
            if len(lines) >= maxins: break
            if stop_at_ret and ins.mnemonic in ('ret', 'int3') and len(lines) > 3:
                break
        return lines

    def strref(self, text):
        hits = []
        for enc in (text.encode(), text.encode('utf-16le')):
            for o in self.find_all(enc + (b'\0' if enc == text.encode() else b'\0\0')):
                hits.append(self.va(o))
        res = []
        for n, v, vs, ro, rs, ch in self.secs:
            if not ch & 0x20000000: continue
            seg = self.data[ro:ro + rs]
            for h in hits:
                if self.x64:
                    # rip-relative disp32: scan for any 4-byte value d such that addr+len+d == h
                    for i in range(len(seg) - 7):
                        pass
                else:
                    for o in self.find_all(struct.pack('<I', h)):
                        if ro <= o < ro + rs: res.append((h, self.va(o)))
        if self.x64:
            res += self.riprefs(hits)
        return res

    def riprefs(self, targets):
        import numpy as np
        res = []
        for n, v, vs, ro, rs, ch in self.secs:
            if not ch & 0x20000000: continue
            seg = np.frombuffer(self.data[ro:ro + rs], dtype=np.uint8)
            if len(seg) < 8: continue
            d = seg[:-3].astype(np.int64) | (seg[1:-2].astype(np.int64) << 8) | (seg[2:-1].astype(np.int64) << 16) | (seg[3:].astype(np.int64) << 24)
            d = np.where(d >= 2**31, d - 2**32, d)
            pos = np.arange(len(d), dtype=np.int64) + v
            for t in targets:
                # displacement typically ends the instruction (lea r, [rip+d]) -> next = pos+4
                idx = np.nonzero(pos + 4 + d == t)[0]
                for i in idx: res.append((t, int(pos[i])))
        return res

    def func_start(self, va):
        # walk back to int3/cc padding boundary
        p = va
        for _ in range(0x4000):
            if self.read(p - 1, 1) == b'\xcc' and self.read(p - 2, 1) in (b'\xcc', b'\xc3'):
                return p
            p -= 1
        return None

if __name__ == '__main__':
    cmd, path = sys.argv[1], sys.argv[2]
    im = Img(path)
    if cmd == 'natives':
        for n, ref, fn in im.natives(sys.argv[3]): print('%-70s table@%x  fn=%x' % (n, ref, fn))
    elif cmd == 'dis':
        print('\n'.join(im.dis(int(sys.argv[3], 16), int(sys.argv[4]) if len(sys.argv) > 4 else 400)))
    elif cmd == 'strref':
        for t, at in im.strref(sys.argv[3]):
            fs = im.func_start(at)
            print('str@%x  ref@%x  func~%x' % (t, at, fs or 0))
