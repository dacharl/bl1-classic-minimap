"""Minimal UE3 (BL1, v584/v594) package reader for uncompressed packages, and the movie inside one.

The in-game build reads the player's own GfxHUD.upk and menus_ingame_redux.upk with this (PLAN_V13);
tools/upk.py lists a package's exports: python -I tools/upk.py <package> [regex]
"""
import re
import struct
import sys

StructError = struct.error      # a plain name: Cosmic Ray's ExceptionReplacer fails on `except (…, struct.error)` (PHASE3 3cf)


class PackageError(ValueError):
    pass


class Pkg:
    def __init__(self, path=None, data=None):
        if data is None:
            with open(path, 'rb') as f:
                data = f.read()
        self.d = d = data
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


def find_export(pk, path):
    for i, e in enumerate(pk.exports, 1):
        if pk.path(i) == path:
            return i, e
    raise PackageError('export %r not found' % path)


def walk_tags(pk, b, p):
    """Yield (name, type, tag_pos, data_pos, size) for a serialized property list until None."""
    while True:
        name = pk.fname(*struct.unpack_from('<ii', b, p))
        if name == 'None':
            return
        typ = pk.fname(*struct.unpack_from('<ii', b, p + 8))
        size = struct.unpack_from('<i', b, p + 16)[0]
        q = p + 24
        if typ == 'StructProperty':
            q += 8
        elif typ == 'BoolProperty':
            q += 4  # v584/v594 store the bool value as an int32 after a size-0 tag
        yield name, typ, p, q, size
        p = q + size


def raw_data_span(pk, export):
    """(tag_pos, data_pos, size) of the RawData ArrayProperty, relative to the export start."""
    b = pk.d[export['off']:export['off'] + export['size']]
    for name, typ, tp, dp, size in walk_tags(pk, b, 4):  # skip NetIndex
        if name == 'RawData' and typ == 'ArrayProperty':
            return tp, dp, size
    raise PackageError('RawData not found in export')


def extract(pk, path):
    _, e = find_export(pk, path)
    tp, dp, size = raw_data_span(pk, e)
    base = e['off'] + dp
    count = struct.unpack_from('<i', pk.d, base)[0]
    if count != size - 4:
        raise PackageError('RawData length %d does not match its property size %d' % (count, size))
    return pk.d[base + 4:base + 4 + count]


def movie(data, path='FlashMovie.HUD'):
    """The GFx movie bytes inside package bytes; PackageError when they aren't an uncompressed package movie."""
    try:
        out = extract(Pkg(data=data), path)
    except PackageError:
        raise
    except (StructError, IndexError, KeyError, UnicodeDecodeError) as ex:
        raise PackageError('unreadable package (%s)' % type(ex).__name__) from None
    if out[:3] not in (b'GFX', b'FWS'):
        raise PackageError('%s is not an uncompressed GFx movie' % path)
    return out


def main():
    pk = Pkg(sys.argv[1])
    pat = re.compile(sys.argv[2], re.I) if len(sys.argv) > 2 else None
    print('ver', pk.ver, 'names', pk.name_count, 'exports', pk.exp_count, 'imports', pk.imp_count)
    for i, e in enumerate(pk.exports, 1):
        full = pk.path(i)
        if pat is None or pat.search(full):
            print('%6d %-22s %-70s size=%-7d off=0x%x' % (i, pk.clsname(e), full, e['size'], e['off']))


if __name__ == '__main__':
    main()
