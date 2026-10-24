"""Minimal UE3 (BL1, v584/v594) package table reader for uncompressed packages."""
import struct, sys, re

class Pkg:
    def __init__(self, path):
        self.d = d = open(path, 'rb').read()
        self.ver = struct.unpack_from('<H', d, 4)[0]
        p = 12
        n = struct.unpack_from('<i', d, p)[0]; p += 4 + n
        p += 4  # package flags
        (self.name_count, self.name_off, self.exp_count, self.exp_off,
         self.imp_count, self.imp_off) = struct.unpack_from('<6i', d, p)
        self.names = []
        p = self.name_off
        for _ in range(self.name_count):
            s, p = self.fstring(p)
            p += 8
            self.names.append(s)
        self.imports = []
        p = self.imp_off
        for _ in range(self.imp_count):
            cp, cpn, cn, cnn, outer, on, onn = struct.unpack_from('<7i', d, p); p += 28
            self.imports.append(dict(cls=self.names[cn], pkg=self.names[cp], outer=outer, name=self.fname(on, onn)))
        self.exports = []
        p = self.exp_off
        for _ in range(self.exp_count):
            pos = p  # start of this export-table entry (SerialSize at +32, SerialOffset at +36)
            ci, si, outer, on, onn, arch = struct.unpack_from('<6i', d, p); p += 24
            flags = struct.unpack_from('<Q', d, p)[0]; p += 8
            size, off = struct.unpack_from('<2i', d, p); p += 8
            p += 4  # export flags (BL1 has no component map here)
            gn = struct.unpack_from('<i', d, p)[0]; p += 4 + 4 * gn
            p += 16 + 4  # guid + package flags
            self.exports.append(dict(cls=ci, sup=si, outer=outer, name=self.fname(on, onn), size=size, off=off,
                                     flags=flags, pos=pos))

    def fstring(self, p):
        n = struct.unpack_from('<i', self.d, p)[0]; p += 4
        if n < 0:
            s = self.d[p:p - 2 * n].decode('utf-16le', 'replace').rstrip('\0'); p += -2 * n
        else:
            s = self.d[p:p + n].decode('latin-1').rstrip('\0'); p += n
        return s, p

    def fname(self, i, num):
        s = self.names[i]
        return s if num == 0 else '%s_%d' % (s, num - 1)

    def objname(self, idx):
        if idx == 0: return ''
        if idx > 0: return self.exports[idx - 1]['name']
        return self.imports[-idx - 1]['name']

    def path(self, idx):
        parts = []
        while idx:
            parts.append(self.objname(idx))
            idx = self.exports[idx - 1]['outer'] if idx > 0 else self.imports[-idx - 1]['outer']
        return '.'.join(reversed(parts))

    def clsname(self, e):
        return self.objname(e['cls']) or 'Class'

if __name__ == '__main__':
    pk = Pkg(sys.argv[1])
    pat = re.compile(sys.argv[2], re.I) if len(sys.argv) > 2 else None
    print('ver', pk.ver, 'names', pk.name_count, 'exports', pk.exp_count, 'imports', pk.imp_count)
    for i, e in enumerate(pk.exports, 1):
        full = pk.path(i)
        if pat is None or pat.search(full):
            print('%6d %-22s %-70s size=%-7d off=0x%x' % (i, pk.clsname(e), full, e['size'], e['off']))
