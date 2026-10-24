"""Dump the tagged (default) properties of objects in a decompressed UE3 package (BL1 v584/v594).

Usage: python -I tools/upkprops.py tools/pk/C_WillowGame.u '^Default__WillowGFxHelperMap$'
Simple values are decoded (int, float, bool, byte, name, str, object); structs and arrays are shown as
raw sizes, except arrays of floats and fixed StrProperty arrays (ArrayIndex), which are expanded.
"""
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from upk import Pkg  # noqa: E402


def props(pk, e):
    d, p, end = pk.d, e['off'], e['off'] + e['size']
    p += 4                                    # NetIndex
    out = []
    while p + 8 <= end:
        ni, nn = struct.unpack_from('<ii', d, p)
        if not 0 <= ni < len(pk.names):
            break
        name = pk.fname(ni, nn)
        p += 8
        if name == 'None':
            break
        ti = struct.unpack_from('<i', d, p)[0]; p += 8
        typ = pk.names[ti]
        size, idx = struct.unpack_from('<ii', d, p); p += 8
        if typ == 'StructProperty':
            sname = pk.names[struct.unpack_from('<i', d, p)[0]]; p += 8
            typ = 'Struct<%s>' % sname
        if typ == 'BoolProperty':
            val = bool(d[p]); p += 1 if pk.ver >= 673 else 4
            out.append((name, idx, typ, val))
            continue
        if typ == 'ByteProperty' and pk.ver >= 633:
            p += 8
        raw = d[p:p + size]; p += size
        if typ == 'IntProperty':
            val = struct.unpack('<i', raw)[0]
        elif typ == 'FloatProperty':
            val = struct.unpack('<f', raw)[0]
        elif typ == 'ByteProperty':
            val = raw[0] if size == 1 else pk.fname(*struct.unpack('<ii', raw))
        elif typ == 'NameProperty':
            val = pk.fname(*struct.unpack('<ii', raw))
        elif typ == 'StrProperty':
            val = pk.fstring(e['off'] * 0 + (p - size))[0] if size else ''
        elif typ == 'ObjectProperty':
            val = pk.path(struct.unpack('<i', raw)[0])
        elif typ == 'ArrayProperty':
            n = struct.unpack_from('<i', raw, 0)[0]
            val = '[%d items, %d bytes]' % (n, size)
            if n and (size - 4) == 4 * n:
                val += ' floats ' + str([round(x, 4) for x in struct.unpack_from('<%df' % n, raw, 4)])
        else:
            val = '<%d bytes>' % size
        out.append((name, idx, typ, val))
    return out


def main():
    pk = Pkg(sys.argv[1])
    pat = re.compile(sys.argv[2])
    for i, e in enumerate(pk.exports, 1):
        if pat.search(pk.path(i)):
            print('==', pk.path(i))
            for name, idx, typ, val in props(pk, e):
                print('  %s%s (%s) = %r' % (name, '[%d]' % idx if idx else '', typ, val))


if __name__ == '__main__':
    main()
