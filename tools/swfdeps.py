"""Dependency closure of a character in a SWF/GFx movie: every character it places, every bitmap a
shape fills with, every font a text field uses, and what kind of definition each one is.
Usage: python -I tools/swfdeps.py movie.gfx <character id> [<character id> ...]
"""
import struct
import sys

SHAPES = {2: 1, 22: 2, 32: 3, 83: 4}          # DefineShape tag -> version
DEFINES = {2, 22, 32, 83, 39, 6, 20, 21, 35, 36, 90, 10, 48, 75, 11, 33, 37, 7, 34, 46, 84, 14, 18,
           1001, 1003, 1005, 1008, 1009}
NAMES = {2: 'Shape', 22: 'Shape2', 32: 'Shape3', 83: 'Shape4', 39: 'Sprite', 6: 'BitsJPEG', 20: 'BitsLossless',
         21: 'BitsJPEG2', 35: 'BitsJPEG3', 36: 'BitsLossless2', 90: 'BitsJPEG4', 10: 'Font', 48: 'Font2',
         75: 'Font3', 11: 'Text', 33: 'Text2', 37: 'EditText', 7: 'Button', 34: 'Button2', 46: 'MorphShape',
         84: 'MorphShape2', 14: 'Sound', 1001: 'GFxExternalImage', 1003: 'GFxGradientImage',
         1005: 'GFxCompactedFont', 1008: 'GFxSubImage', 1009: 'GFxExternalImage2'}


class Bits:
    def __init__(self, b, pos=0):
        self.b, self.p = b, pos * 8

    def u(self, n):
        v = 0
        for _ in range(n):
            v = (v << 1) | ((self.b[self.p >> 3] >> (7 - (self.p & 7))) & 1)
            self.p += 1
        return v

    def s(self, n):
        v = self.u(n)
        return v - (1 << n) if n and v & (1 << (n - 1)) else v

    def align(self):
        self.p = (self.p + 7) & ~7
        return self.p >> 3


def read_tags(d, p, end):
    out = []
    while p < end:
        hdr = struct.unpack_from('<H', d, p)[0]; p += 2
        code, ln = hdr >> 6, hdr & 0x3F
        if ln == 0x3F:
            ln = struct.unpack_from('<I', d, p)[0]; p += 4
        out.append((code, d[p:p + ln])); p += ln
        if code == 0:
            break
    return out


def skip_rect(b, p):
    return p + (5 + 4 * (b[p] >> 3) + 7) // 8


def skip_matrix(br):
    if br.u(1):
        n = br.u(5); br.u(n); br.u(n)
    if br.u(1):
        n = br.u(5); br.u(n); br.u(n)
    n = br.u(5); br.u(n); br.u(n)
    br.align()


def read_fills(b, p, ver, bitmaps):
    n = b[p]; p += 1
    if n == 0xFF and ver >= 2:
        n = struct.unpack_from('<H', b, p)[0]; p += 2
    for _ in range(n):
        t = b[p]; p += 1
        if t == 0x00:
            p += 4 if ver >= 3 else 3
        elif t in (0x10, 0x12, 0x13):
            br = Bits(b, p); skip_matrix(br); p = br.p >> 3
            k = b[p] & 0x0F; p += 1 + k * (5 if ver >= 3 else 4)
            if t == 0x13:
                p += 2
        elif 0x40 <= t <= 0x43:
            bitmaps.add(struct.unpack_from('<H', b, p)[0]); p += 2
            br = Bits(b, p); skip_matrix(br); p = br.p >> 3
        else:
            raise ValueError('fill type %#x' % t)
    return p


def read_lines(b, p, ver, bitmaps):
    n = b[p]; p += 1
    if n == 0xFF:
        n = struct.unpack_from('<H', b, p)[0]; p += 2
    for _ in range(n):
        if ver < 4:
            p += 2 + (4 if ver >= 3 else 3)
        else:
            p += 2
            f1 = b[p]; f2 = b[p + 1]; p += 2
            if (f1 >> 4) & 3 == 2:  # miter join
                p += 2
            if f1 & 0x08:            # has fill
                p = read_fills(b[:p] + bytes([1]) + b[p:], p, ver, bitmaps) - 1
            else:
                p += 4
    return p


def shape_bitmaps(code, b):
    ver = SHAPES[code]
    bitmaps = set()
    p = skip_rect(b, 2)
    if ver == 4:
        p = skip_rect(b, p) + 1
    p = read_fills(b, p, ver, bitmaps)
    p = read_lines(b, p, ver, bitmaps)
    br = Bits(b, p)
    nf, nl = br.u(4), br.u(4)
    while True:
        if br.u(1):  # edge
            straight = br.u(1); n = br.u(4) + 2
            if straight:
                if br.u(1):
                    br.u(n); br.u(n)
                else:
                    br.u(1); br.u(n)
            else:
                br.u(n); br.u(n); br.u(n); br.u(n)
            continue
        flags = br.u(5)
        if flags == 0:
            break
        if flags & 1:
            n = br.u(5); br.u(n); br.u(n)
        if flags & 2:
            br.u(nf)
        if flags & 4:
            br.u(nf)
        if flags & 8:
            br.u(nl)
        if flags & 16:
            q = br.align()
            q = read_fills(b, q, ver, bitmaps)
            q = read_lines(b, q, ver, bitmaps)
            br = Bits(b, q)
            nf, nl = br.u(4), br.u(4)
    return bitmaps


class Movie:
    def __init__(self, path=None, data=None):
        d = data if data is not None else open(path, 'rb').read()
        p = skip_rect(d, 8) + 4
        self.defs, self.exports, self.imports = {}, {}, {}
        self._scan(read_tags(d, p, len(d)))

    def _scan(self, tags):
        for code, b in tags:
            if code in DEFINES and len(b) >= 2:
                self.defs.setdefault(struct.unpack_from('<H', b, 0)[0], (code, b))
            if code == 39:
                self._scan(read_tags(b, 4, len(b)))
            if code == 56:
                n = struct.unpack_from('<H', b, 0)[0]; q = 2
                for _ in range(n):
                    cid = struct.unpack_from('<H', b, q)[0]; q += 2
                    j = b.index(b'\0', q); self.exports[cid] = b[q:j].decode('latin-1'); q = j + 1
            if code == 57:
                j = b.index(b'\0'); url = b[:j].decode('latin-1'); q = j + 1
                n = struct.unpack_from('<H', b, q)[0]; q += 2
                for _ in range(n):
                    cid = struct.unpack_from('<H', b, q)[0]; q += 2
                    j = b.index(b'\0', q); self.imports[cid] = (url, b[q:j].decode('latin-1')); q = j + 1

    def refs(self, cid):
        code, b = self.defs[cid]
        out = set()
        if code == 39:
            for c, tb in read_tags(b, 4, len(b)):
                if c in (26, 70) and tb[0] & 0x02:
                    out.add(struct.unpack_from('<H', tb, 3 if c == 26 else 4 + (0 if not tb[1] & 0x08 else 0))[0])
                elif c == 4:
                    out.add(struct.unpack_from('<H', tb, 0)[0])
        elif code in SHAPES:
            out |= shape_bitmaps(code, b)
        elif code == 37:
            p = skip_rect(b, 2)
            flags = struct.unpack_from('<H', b, p)[0]
            if flags & 0x0001:  # HasFont
                out.add(struct.unpack_from('<H', b, p + 2)[0])
        elif code in (7, 34):
            p = 2 + (1 if code == 34 else 0) + (2 if code == 34 else 0)
            while b[p]:
                out.add(struct.unpack_from('<H', b, p + 1)[0])
                q = p + 5
                br = Bits(b, q); skip_matrix(br); q = br.p >> 3
                if code == 34:
                    br = Bits(b, q)
                    ha, hm, n = br.u(1), br.u(1), br.u(4)
                    for _ in range(4 * (ha + hm)):
                        br.u(n)
                    q = br.align()
                p = q
        return out

    def closure(self, roots):
        seen, todo = set(), list(roots)
        while todo:
            c = todo.pop()
            if c in seen:
                continue
            seen.add(c)
            if c in self.defs:
                todo.extend(self.refs(c) - seen)
        return seen


def main():
    m = Movie(sys.argv[1])
    roots = [int(a) for a in sys.argv[2:]]
    ids = m.closure(roots)
    kinds, total, missing = {}, 0, []
    for c in sorted(ids):
        if c in m.defs:
            code, b = m.defs[c]
            kinds.setdefault(NAMES.get(code, str(code)), []).append(c)
            total += len(b)
        elif c in m.imports:
            kinds.setdefault('Imported', []).append(c)
        else:
            missing.append(c)
    print('closure of %s: %d characters, %d bytes of definitions' % (roots, len(ids), total))
    for k, v in sorted(kinds.items()):
        print('  %-18s %4d  %s' % (k, len(v), v if len(v) <= 12 else v[:12] + ['...']))
    for c in kinds.get('GFxExternalImage', []):
        b = m.defs[c][1]
        print('    external image %d -> %s' % (c, b[10:10 + b[9]].decode('latin-1') or b[9 + 1 + b[9] + 1:].split(b'\0')[0]))
    for c in kinds.get('Imported', []):
        print('    imported %d -> %s' % (c, m.imports[c]))
    for c in sorted(set(kinds.get('Font3', []) + kinds.get('Font2', []) + kinds.get('GFxCompactedFont', []))):
        print('    font %d' % c)
    if missing:
        print('  undefined ids: %s' % missing)


if __name__ == '__main__':
    main()
