"""Minimal SWF/GFx (AS2) dumper: sprite tree, instance names, exports, and AS2 action listings.
Usage: python -I swfdump.py movie.gfx > out.txt
"""
import struct, sys

ACTIONS = {
    0x04: 'NextFrame', 0x05: 'PrevFrame', 0x06: 'Play', 0x07: 'Stop', 0x0A: 'Add', 0x0B: 'Subtract',
    0x0C: 'Multiply', 0x0D: 'Divide', 0x0E: 'Equals', 0x0F: 'Less', 0x10: 'And', 0x11: 'Or', 0x12: 'Not',
    0x13: 'StringEquals', 0x14: 'StringLength', 0x15: 'StringExtract', 0x17: 'Pop', 0x18: 'ToInteger',
    0x1C: 'GetVariable', 0x1D: 'SetVariable', 0x20: 'SetTarget2', 0x21: 'StringAdd', 0x22: 'GetProperty',
    0x23: 'SetProperty', 0x24: 'CloneSprite', 0x25: 'RemoveSprite', 0x26: 'Trace', 0x27: 'StartDrag',
    0x28: 'EndDrag', 0x29: 'StringLess', 0x2A: 'Throw', 0x2B: 'CastOp', 0x2C: 'ImplementsOp', 0x30: 'RandomNumber',
    0x34: 'GetTime', 0x3A: 'Delete', 0x3B: 'Delete2', 0x3C: 'DefineLocal', 0x3D: 'CallFunction', 0x3E: 'Return',
    0x3F: 'Modulo', 0x40: 'NewObject', 0x41: 'DefineLocal2', 0x42: 'InitArray', 0x43: 'InitObject', 0x44: 'TypeOf',
    0x45: 'TargetPath', 0x46: 'Enumerate', 0x47: 'Add2', 0x48: 'Less2', 0x49: 'Equals2', 0x4A: 'ToNumber',
    0x4B: 'ToString', 0x4C: 'PushDuplicate', 0x4D: 'StackSwap', 0x4E: 'GetMember', 0x4F: 'SetMember',
    0x50: 'Increment', 0x51: 'Decrement', 0x52: 'CallMethod', 0x53: 'NewMethod', 0x54: 'InstanceOf',
    0x55: 'Enumerate2', 0x60: 'BitAnd', 0x61: 'BitOr', 0x62: 'BitXor', 0x63: 'BitLShift', 0x64: 'BitRShift',
    0x65: 'BitURShift', 0x66: 'StrictEquals', 0x67: 'Greater', 0x68: 'StringGreater', 0x69: 'Extends',
    0x81: 'GotoFrame', 0x83: 'GetURL', 0x87: 'StoreRegister', 0x88: 'ConstantPool', 0x8A: 'WaitForFrame',
    0x8B: 'SetTarget', 0x8C: 'GoToLabel', 0x8D: 'WaitForFrame2', 0x8E: 'DefineFunction2', 0x8F: 'Try',
    0x94: 'With', 0x96: 'Push', 0x99: 'Jump', 0x9A: 'GetURL2', 0x9B: 'DefineFunction', 0x9D: 'If',
    0x9E: 'Call', 0x9F: 'GotoFrame2',
}

def cstr(b, p):
    j = b.index(b'\0', p); return b[p:j].decode('latin-1'), j + 1

def dis_actions(b, out, indent='    '):
    pool = []
    p = 0
    while p < len(b):
        start = p
        op = b[p]; p += 1
        if op == 0:
            break
        ln = 0
        if op >= 0x80:
            ln = struct.unpack_from('<H', b, p)[0]; p += 2
        body = b[p:p + ln]; p += ln
        name = ACTIONS.get(op, 'op%02x' % op)
        arg = ''
        if op == 0x88:
            n = struct.unpack_from('<H', body, 0)[0]; q = 2; pool = []
            for _ in range(n):
                s, q = cstr(body, q); pool.append(s)
            arg = '%d entries' % n
        elif op == 0x96:
            q = 0; vals = []
            while q < len(body):
                t = body[q]; q += 1
                if t == 0: s, q = cstr(body, q); vals.append(repr(s))
                elif t == 1: vals.append(repr(round(struct.unpack_from('<f', body, q)[0], 4))); q += 4
                elif t == 2: vals.append('null')
                elif t == 3: vals.append('undefined')
                elif t == 4: vals.append('r%d' % body[q]); q += 1
                elif t == 5: vals.append('true' if body[q] else 'false'); q += 1
                elif t == 6:
                    hi, lo = struct.unpack_from('<II', body, q); q += 8
                    vals.append(repr(struct.unpack('<d', struct.pack('<II', lo, hi))[0]))
                elif t == 7: vals.append(str(struct.unpack_from('<i', body, q)[0])); q += 4
                elif t == 8: i = body[q]; q += 1; vals.append(repr(pool[i]) if i < len(pool) else 'c%d' % i)
                elif t == 9: i = struct.unpack_from('<H', body, q)[0]; q += 2; vals.append(repr(pool[i]) if i < len(pool) else 'c%d' % i)
                else: vals.append('?%d' % t); break
            arg = ', '.join(vals)
        elif op in (0x9B, 0x8E):
            fn, q = cstr(body, 0)
            nparams = struct.unpack_from('<H', body, q)[0]; q += 2
            params = []
            if op == 0x9B:
                for _ in range(nparams):
                    s, q = cstr(body, q); params.append(s)
            else:
                q += 1 + 2  # register count + flags
                for _ in range(nparams):
                    _reg = body[q]; q += 1  # parameter register (not printed)
                    s, q = cstr(body, q); params.append(s)
            codesize = struct.unpack_from('<H', body, q)[0]
            out.append('%sfunction %s(%s) {' % (indent, fn, ', '.join(params)))
            sub = b[p:p + codesize]
            dis_actions_with_pool(sub, out, indent + '  ', pool)
            out.append('%s}' % indent)
            p += codesize
            continue
        elif op in (0x99, 0x9D):
            arg = 'off %+d' % struct.unpack_from('<h', body, 0)[0]
        elif op == 0x83:
            u, q = cstr(body, 0); t, q = cstr(body, q); arg = '%r %r' % (u, t)
        elif op == 0x8C:
            arg = repr(cstr(body, 0)[0])
        elif op == 0x87:
            arg = 'r%d' % body[0]
        elif op == 0x81:
            arg = str(struct.unpack_from('<H', body, 0)[0])
        out.append('%s%04x %s %s' % (indent, start, name, arg))

def dis_actions_with_pool(b, out, indent, pool):
    # functions share the enclosing constant pool
    saved = list(pool)
    tmp = []
    _dis_with(b, tmp, indent, saved)
    out.extend(tmp)

def _dis_with(b, out, indent, pool):
    # prepend a fake ConstantPool so the shared pool is visible
    hdr = bytearray([0x88]); body = bytearray(struct.pack('<H', len(pool)))
    for s in pool: body += s.encode('latin-1') + b'\0'
    hdr += struct.pack('<H', len(body)) + body
    lines = []
    dis_actions(bytes(hdr) + b, lines, indent)
    out.extend(lines[1:])


class Swf:
    def __init__(self, path):
        d = open(path, 'rb').read()
        self.d = d
        nbits = d[8] >> 3
        rect_bytes = (5 + 4 * nbits + 7) // 8
        p = 8 + rect_bytes + 4
        self.out = []
        self.sprite_names = {}
        self.walk(d, p, len(d), 'root', 0)

    def walk(self, d, p, end, owner, depth):
        frame = 0
        ind = '  ' * depth
        while p < end:
            hdr = struct.unpack_from('<H', d, p)[0]; p += 2
            code = hdr >> 6; ln = hdr & 0x3F
            if ln == 0x3F:
                ln = struct.unpack_from('<I', d, p)[0]; p += 4
            body = d[p:p + ln]; p += ln
            if code == 0:
                break
            if code == 1:
                frame += 1
            elif code == 39:  # DefineSprite
                sid = struct.unpack_from('<H', body, 0)[0]
                self.out.append('%sDefineSprite %d' % (ind, sid))
                self.walk(body, 4, len(body), 'sprite%d' % sid, depth + 1)
            elif code == 43:  # FrameLabel
                self.out.append('%s[%s frame %d] label %r' % (ind, owner, frame, cstr(body, 0)[0]))
            elif code in (56, 57):  # ExportAssets / ImportAssets
                n = struct.unpack_from('<H', body, 0)[0]; q = 2
                if code == 57:
                    url, q = cstr(body, 0); n = struct.unpack_from('<H', body, q)[0]; q += 2
                    self.out.append('%sImportAssets from %r' % (ind, url))
                for _ in range(n):
                    cid = struct.unpack_from('<H', body, q)[0]; q += 2
                    s, q = cstr(body, q)
                    self.sprite_names[cid] = s
                    self.out.append('%s%s %d -> %r' % (ind, 'Export' if code == 56 else 'Import', cid, s))
            elif code in (26, 70):  # PlaceObject2/3
                flags = body[0]; q = 1
                flags2 = 0
                if code == 70: flags2 = body[1]; q = 2
                dep = struct.unpack_from('<H', body, q)[0]; q += 2
                if code == 70 and (flags2 & 0x08 or (flags2 & 0x10 and flags & 0x02)):
                    cname, q = cstr(body, q)  # class name
                cid = None
                if flags & 0x02: cid = struct.unpack_from('<H', body, q)[0]; q += 2
                name = None
                if flags & 0x20:
                    # skip matrix / cxform / ratio
                    if flags & 0x04:
                        q = self.skip_matrix(body, q)
                    if flags & 0x08:
                        q = self.skip_cxform(body, q)
                    if flags & 0x10: q += 2
                    name, q = cstr(body, q)
                if name:
                    self.out.append('%s[%s frame %d] place char %s as %r depth %d' % (ind, owner, frame, cid, name, dep))
            elif code == 12:  # DoAction
                self.out.append('%s[%s frame %d] DoAction' % (ind, owner, frame))
                dis_actions(body, self.out, ind + '    ')
            elif code == 59:  # DoInitAction
                sid = struct.unpack_from('<H', body, 0)[0]
                self.out.append('%s[DoInitAction sprite %d]' % (ind, sid))
                dis_actions(body[2:], self.out, ind + '    ')

    @staticmethod
    def bits(body, q):
        return BitReader(body, q)

    def skip_matrix(self, body, q):
        br = BitReader(body, q)
        if br.u(1): n = br.u(5); br.u(n); br.u(n)
        if br.u(1): n = br.u(5); br.u(n); br.u(n)
        n = br.u(5); br.u(n); br.u(n)
        return br.align()

    def skip_cxform(self, body, q):
        br = BitReader(body, q)
        ha = br.u(1); hm = br.u(1); n = br.u(4)
        if hm: [br.u(n) for _ in range(4)]
        if ha: [br.u(n) for _ in range(4)]
        return br.align()

class BitReader:
    def __init__(self, b, q):
        self.b = b; self.pos = q * 8
    def u(self, n):
        v = 0
        for _ in range(n):
            byte = self.b[self.pos >> 3]
            v = (v << 1) | ((byte >> (7 - (self.pos & 7))) & 1)
            self.pos += 1
        return v
    def align(self):
        return (self.pos + 7) >> 3

if __name__ == '__main__':
    s = Swf(sys.argv[1])
    print('\n'.join(s.out))
