"""Timeline of a sprite (or the root): per frame, its label and each PlaceObject2/3 with the full matrix.

Usage: python -I tools/swftimeline.py movie.gfx <sprite id | root> [--frames a-b] [--names]
Matrix printed as sx, r0 (skew 0), r1 (skew 1), sy, tx, ty in pixels (twips / 20); a nonzero r0/r1 with
unequal sign is a skew, equal-magnitude opposite r0/r1 with sx == sy is a rotation.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from swfdeps import Bits, Movie, read_tags, skip_rect  # noqa: E402


def matrix(b, p):
    br = Bits(b, p)
    sx = sy = 1.0
    r0 = r1 = 0.0
    if br.u(1):
        n = br.u(5); sx = br.s(n) / 65536.0; sy = br.s(n) / 65536.0
    if br.u(1):
        n = br.u(5); r0 = br.s(n) / 65536.0; r1 = br.s(n) / 65536.0
    n = br.u(5); tx = br.s(n) / 20.0; ty = br.s(n) / 20.0
    return (sx, r0, r1, sy, tx, ty), br.align()


def place(code, b):
    flags = b[0]
    p = 1
    flags2 = 0
    if code == 70:
        flags2 = b[1]; p = 2
    depth = struct.unpack_from('<H', b, p)[0]; p += 2
    if code == 70 and flags2 & 0x08:          # class name
        p = b.index(b'\0', p) + 1
    cid = None
    if flags & 0x02:
        cid = struct.unpack_from('<H', b, p)[0]; p += 2
    m = None
    if flags & 0x04:
        m, p = matrix(b, p)
    if flags & 0x08:                          # colour transform with alpha: skip
        br = Bits(b, p); has_add, has_mul = br.u(1), br.u(1); n = br.u(4)
        br.u(n * 4 * (has_add + has_mul)); p = br.align()
    if flags & 0x10:
        p += 2                                # ratio
    name = None
    if flags & 0x20:
        j = b.index(b'\0', p); name = b[p:j].decode('latin-1'); p = j + 1
    return depth, cid, m, name, bool(flags & 0x01)


def main():
    path, which = sys.argv[1], sys.argv[2]
    d = open(path, 'rb').read()
    mv = Movie(data=d)
    if which == 'root':
        tags = read_tags(d, skip_rect(d, 8) + 4, len(d))
    else:
        code, b = mv.defs[int(which)]
        assert code == 39, 'not a sprite'
        tags = read_tags(b, 4, len(b))
    lo, hi = 1, 10 ** 9
    if '--frames' in sys.argv:
        a, _, z = sys.argv[sys.argv.index('--frames') + 1].partition('-')
        lo, hi = int(a), int(z or a)
    frame, label = 1, ''
    for code, b in tags:
        if code == 43:
            label = b.split(b'\0')[0].decode('latin-1')
        elif code in (26, 70) and lo <= frame <= hi:
            depth, cid, m, name, move = place(code, b)
            ms = ('%.3f %.3f %.3f %.3f  %.1f %.1f' % m) if m else '-'
            print('f%-4d %-14s d%-4d %s %-6s %-12s %s' % (frame, label, depth, 'move ' if move else 'place',
                                                        cid if cid else '', name or '', ms))
        elif code == 28 and lo <= frame <= hi:
            print('f%-4d %-14s d%-4d remove' % (frame, label, struct.unpack_from('<H', b, 0)[0]))
        elif code == 1:
            frame += 1
            label = ''


if __name__ == '__main__':
    main()
