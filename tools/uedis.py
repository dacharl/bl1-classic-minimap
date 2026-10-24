"""Readable disassembly of BL1 (UE3 v584 classic / v594 Enhanced) UnrealScript functions.
Usage: python -I uedis.py <E|C> <regex over Class.Function paths>
"""
import struct, sys, re, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from upk import Pkg

PK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pk')

def load_func_meta(pk, idx, enhanced):
    e = pk.exports[idx - 1]
    d = pk.d; p = e['off']
    p += 4 + 8  # netindex + None tag
    p += 4      # next
    sup, stext, children, cpp, line, tpos = struct.unpack_from('<6i', d, p); p += 24
    if enhanced:
        _memsize, disksize = struct.unpack_from('<2i', d, p); p += 8
    else:
        disksize = struct.unpack_from('<i', d, p)[0]; p += 4
    code = d[p:p + disksize]; p += disksize
    inative, prec = struct.unpack_from('<HB', d, p); p += 3
    flags = struct.unpack_from('<I', d, p)[0]; p += 4
    return dict(code=code, inative=inative, prec=prec, flags=flags, children=children, sup=sup)

class Dis:
    def __init__(self, pk, enhanced, natives):
        self.pk = pk; self.enh = enhanced; self.natives = natives
        self.ptr = 8 if enhanced else 4

    def run(self, code):
        self.c = code; self.i = 0; self.mem = 0
        lines = self.lines = []
        while self.i < len(self.c):
            m = self.mem
            s = self.expr()
            if s is None: break
            lines.append('  %04x: %s' % (m, s))
        return lines

    # primitive readers keep a parallel "memory offset" so jump targets line up
    def u8(self):
        v = self.c[self.i]; self.i += 1; self.mem += 1; return v
    def u16(self):
        v = struct.unpack_from('<H', self.c, self.i)[0]; self.i += 2; self.mem += 2; return v
    def i32(self):
        v = struct.unpack_from('<i', self.c, self.i)[0]; self.i += 4; self.mem += 4; return v
    def f32(self):
        v = struct.unpack_from('<f', self.c, self.i)[0]; self.i += 4; self.mem += 4; return v
    def obj(self):
        v = struct.unpack_from('<i', self.c, self.i)[0]; self.i += 4; self.mem += self.ptr
        if v == 0: return 'None'
        return self.pk.path(v).split('.')[-1] if v else 'None'
    def objfull(self):
        v = struct.unpack_from('<i', self.c, self.i)[0]; self.i += 4; self.mem += self.ptr
        return self.pk.path(v) if v else 'None'
    def name(self):
        a, b = struct.unpack_from('<ii', self.c, self.i); self.i += 8; self.mem += 8
        return self.pk.fname(a, b)
    def zstr(self):
        j = self.c.index(b'\0', self.i); s = self.c[self.i:j].decode('latin-1')
        self.mem += j + 1 - self.i; self.i = j + 1; return s
    def wstr(self):
        j = self.i
        while self.c[j:j+2] != b'\0\0': j += 2
        s = self.c[self.i:j].decode('utf-16le'); self.mem += j + 2 - self.i; self.i = j + 2; return s
    def params(self):
        a = []
        while True:
            if self.c[self.i] == 0x16:
                self.u8(); break
            a.append(self.expr())
        return ', '.join(a)

    def expr(self):
        t = self.u8()
        E = self.expr
        if t == 0x00: return self.obj()
        if t == 0x01: return self.obj()
        if t == 0x02: return 'Default.' + self.obj()
        if t == 0x04: return 'return ' + E()
        if t == 0x05:
            if self.enh: self.obj()
            self.u8(); return 'switch (%s)' % E()
        if t == 0x06: return 'goto %04x' % self.u16()
        if t == 0x07:
            off = self.u16(); return 'if !(%s) goto %04x' % (E(), off)
        if t == 0x08: return 'stop'
        if t == 0x09:
            self.u16(); self.u8(); return 'assert(%s)' % E()
        if t == 0x0A:
            off = self.u16()
            if off == 0xFFFF: return 'default: (next %04x)' % off
            return 'case %s: (next %04x)' % (E(), off)
        if t == 0x0B: return 'nothing'
        if t == 0x0D: return 'goto label ' + E()
        if t == 0x0E: self.obj(); return E()
        if t == 0x0F: a = E(); b = E(); return '%s = %s' % (a, b)
        if t == 0x10: a = E(); b = E(); return '%s[%s]' % (b, a)
        if t == 0x11: return 'new(%s,%s,%s,%s)' % (E(), E(), E(), E())
        if t in (0x12, 0x19):
            a = E(); self.u16()
            if self.enh: self.obj(); self.u8()
            else: self.u8(); self.u8()
            b = E()
            return '%s%s.%s' % ('class(' if t == 0x12 else '', a, b) + (')' if t == 0x12 else '')
        if t == 0x13: c = self.obj(); return 'class<%s>(%s)' % (c, E())
        if t == 0x14: a = E(); b = E(); return '%s = %s' % (a, b)
        if t == 0x15: return '<endparmvalue>'
        if t == 0x16: return '<endparms>'
        if t == 0x17: return 'self'
        if t == 0x18: self.u16(); return E()
        if t == 0x1A: a = E(); b = E(); return '%s[%s]' % (b, a)
        if t == 0x1B: n = self.name(); return '%s(%s)' % (n, self.params())
        if t == 0x1C: n = self.objfull(); return '%s(%s)' % (n, self.params())
        if t == 0x1D: return str(self.i32())
        if t == 0x1E: return repr(round(self.f32(), 4))
        if t == 0x1F: return '"%s"' % self.zstr()
        if t == 0x20: return self.objfull()
        if t == 0x21: return "'%s'" % self.name()
        if t == 0x22: return 'rot(%d,%d,%d)' % (self.i32(), self.i32(), self.i32())
        if t == 0x23: return 'vect(%s,%s,%s)' % (self.f32(), self.f32(), self.f32())
        if t == 0x24: return str(self.u8())
        if t == 0x25: return '0'
        if t == 0x26: return '1'
        if t == 0x27: return 'true'
        if t == 0x28: return 'false'
        if t == 0x29: return 'nativeparm ' + self.obj()
        if t == 0x2A: return 'None'
        if t == 0x2C: return str(self.u8())
        if t == 0x2D: return E()
        if t == 0x2E: c = self.obj(); return '%s(%s)' % (c, E())
        if t == 0x2F: a = E(); off = self.u16(); return 'foreach %s (end %04x)' % (a, off)
        if t == 0x30: return 'iteratorpop'
        if t == 0x31: return 'iteratornext'
        if t in (0x32, 0x33): self.obj(); a = E(); b = E(); return '(%s %s %s)' % (a, '==' if t == 0x32 else '!=', b)
        if t == 0x34: return 'u"%s"' % self.wstr()
        if t == 0x35:
            f = self.obj(); self.obj(); self.u8(); self.u8(); return '%s.%s' % (E(), f)
        if t == 0x36: return '%s.Length' % E()
        if t == 0x37: n = self.name(); return 'global.%s(%s)' % (n, self.params())
        if t == 0x38: ty = self.u8(); return 'cast%02x(%s)' % (ty, E())
        if t == 0x39: a = E(); b = E(); c = E(); return '%s.Insert(%s,%s)' % (a, b, c)
        if t == 0x3A: self.obj(); return 'return'
        if t in (0x3B, 0x3C, 0x3D, 0x3E):
            a = E(); b = E(); self.u8(); return '(%s %s %s)' % (a, '==' if t in (0x3B, 0x3D) else '!=', b)
        if t == 0x3F: return 'EmptyDelegate'
        if t == 0x40: a = E(); b = E(); c = E(); return '%s.Remove(%s,%s)' % (a, b, c)
        if t == 0x42:
            self.u8(); self.obj(); n = self.name(); return 'delegate %s(%s)' % (n, self.params())
        if t == 0x43: n = self.name(); self.obj(); return 'delegate ' + n
        if t == 0x44: a = E(); b = E(); return '%s = %s' % (a, b)
        if t == 0x45:
            c = E(); self.u16(); a = E(); self.u16(); b = E(); return '(%s ? %s : %s)' % (c, a, b)
        if t == 0x46: a = E(); self.u16(); b = E(); self.u8(); return '%s.Find(%s)' % (a, b)
        if t == 0x47: a = E(); self.u16(); b = E(); c = E(); self.u8(); return '%s.Find(%s,%s)' % (a, b, c)
        if t == 0x48: return 'out ' + self.obj()
        if t == 0x49:
            self.u16(); a = E(); self.u8(); return 'defaultparm(%s)' % a
        if t == 0x4A: return '<emptyparm>'
        if t == 0x4B: return 'delegate ' + self.name()
        if t == 0x51: return E()
        if t == 0x52: c = self.obj(); return '%s(%s)' % (c, E())
        if t == 0x53: return None
        if t == 0x54: a = E(); b = E(); self.u8(); return '%s.Add(%s)' % (a, b)
        if t == 0x55: a = E(); self.u16(); b = E(); self.u8(); return '%s.AddItem(%s)' % (a, b)
        if t == 0x56: a = E(); self.u16(); b = E(); self.u8(); return '%s.RemoveItem(%s)' % (a, b)
        if t == 0x57: a = E(); self.u16(); b = E(); c = E(); self.u8(); return '%s.InsertItem(%s,%s)' % (a, b, c)
        if t == 0x58:
            a = E(); b = E(); has = self.u8(); c = E(); off = self.u16()
            return 'foreach %s(%s%s) (end %04x)' % (a, b, ', ' + c if has else '', off)
        if t == 0x5A: self.u16(); return '<editoronly>'
        if 0x60 <= t < 0x70:
            idx = ((t - 0x60) << 8) + self.u8()
            return '%s(%s)' % (self.natives.get(idx, 'native%d' % idx), self.params())
        if t >= 0x70:
            return '%s(%s)' % (self.natives.get(t, 'native%d' % t), self.params())
        return '<?%02x @%d>' % (t, self.i - 1)


def native_table(tag):
    nat = {}
    for f in ['Core', 'Engine', 'GameFramework', 'GearboxFramework', 'GFxUI', 'WillowGame']:
        pk = Pkg(os.path.join(PK, '%s_%s.u' % (tag, f)))
        for i, e in enumerate(pk.exports, 1):
            if pk.clsname(e) != 'Function': continue
            try:
                m = load_func_meta(pk, i, tag == 'E')
            except Exception:
                continue
            if m['inative']:
                nat[m['inative']] = pk.exports[i - 1]['name']
    return nat


def main():
    tag, pat = sys.argv[1], re.compile(sys.argv[2])
    nat = native_table(tag)
    pk = Pkg(os.path.join(PK, '%s_WillowGame.u' % tag))
    dis = Dis(pk, tag == 'E', nat)
    for i, e in enumerate(pk.exports, 1):
        if pk.clsname(e) != 'Function': continue
        path = pk.path(i)
        if not pat.search(path): continue
        m = load_func_meta(pk, i, tag == 'E')
        params = []
        c = m['children'] if tag == 'E' else struct.unpack_from('<i', pk.d, e['off'] + 20)[0]
        while c > 0:
            ce = pk.exports[c - 1]
            params.append('%s %s' % (pk.clsname(ce).replace('Property', ''), ce['name']))
            # UField::Next is the dword after NetIndex + None tag
            c = struct.unpack_from('<i', pk.d, ce['off'] + (12 if tag == 'E' else 16))[0]
        fl = m['flags']
        kind = []
        if fl & 0x400: kind.append('native')
        if fl & 0x800: kind.append('event')
        if fl & 0x2000: kind.append('static')
        if fl & 0x40: kind.append('net')
        print('\n%s function %s(%s)' % (' '.join(kind), path, '; '.join(params)))
        try:
            for l in dis.run(m['code']): print(l)
        except Exception as ex:
            for l in dis.lines: print(l)
            print('  !! decode error', ex, 'at byte', dis.i, dis.c[max(0,dis.i-24):dis.i+24].hex(' '))

if __name__ == '__main__':
    main()
