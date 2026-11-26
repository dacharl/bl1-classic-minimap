"""Dependency closure of a character in a SWF/GFx movie: every character it places, every bitmap a
shape fills with, every font a text field uses, and what kind of definition each one is.
Usage: python -I tools/swfdeps.py movie.gfx <character id> [<character id> ...]
"""

import sys

try:        # inside the mod package (the in-game build, PLAN_V13)
    from .swfmerge import (DEFINES, SHAPES, Bits, read_fills, read_lines, read_tags, u16,  # noqa: F401
                           shape_gradient_count, skip_matrix, skip_rect, walk_shape)
except ImportError:     # a plain module (tools/ wrappers, offline suites)
    from swfmerge import (DEFINES, SHAPES, Bits, read_fills, read_lines, read_tags, u16,  # noqa: F401
                          shape_gradient_count, skip_matrix, skip_rect, walk_shape)

NAMES = {2: 'Shape', 22: 'Shape2', 32: 'Shape3', 83: 'Shape4', 39: 'Sprite', 6: 'BitsJPEG', 20: 'BitsLossless',
         21: 'BitsJPEG2', 35: 'BitsJPEG3', 36: 'BitsLossless2', 90: 'BitsJPEG4', 10: 'Font', 48: 'Font2',
         75: 'Font3', 11: 'Text', 33: 'Text2', 37: 'EditText', 7: 'Button', 34: 'Button2', 46: 'MorphShape',
         84: 'MorphShape2', 14: 'Sound', 1001: 'GFxExternalImage', 1003: 'GFxGradientImage',
         1005: 'GFxCompactedFont', 1008: 'GFxSubImage', 1009: 'GFxExternalImage2'}


def shape_bitmaps(code, b):
    return walk_shape(code, b)[0]


class Movie:
    def __init__(self, path=None, data=None):
        if data is None:
            with open(path, 'rb') as f:
                data = f.read()
        d = data
        p = skip_rect(d, 8) + 4
        self.defs, self.exports, self.imports = {}, {}, {}
        self._scan(read_tags(d, p, len(d)))

    def _scan(self, tags):
        for code, b in tags:
            if code in DEFINES and len(b) >= 2:
                self.defs.setdefault(u16(b, 0), (code, b))
            if code == 39:
                self._scan(read_tags(b, 4, len(b)))
            if code == 56:
                n = u16(b, 0); q = 2
                for _ in range(n):
                    cid = u16(b, q); q += 2
                    j = b.index(b'\0', q); self.exports[cid] = b[q:j].decode('latin-1'); q = j + 1
            if code == 57:
                j = b.index(b'\0'); url = b[:j].decode('latin-1'); q = j + 1
                n = u16(b, q); q += 2
                for _ in range(n):
                    cid = u16(b, q); q += 2
                    j = b.index(b'\0', q); self.imports[cid] = (url, b[q:j].decode('latin-1')); q = j + 1

    def refs(self, cid):
        code, b = self.defs[cid]
        out = set()
        if code == 39:
            for c, tb in read_tags(b, 4, len(b)):
                if c in (26, 70) and tb[0] & 0x02:
                    out.add(u16(tb, 3 if c == 26 else 4 + (0 if not tb[1] & 0x08 else 0)))
                elif c == 4:
                    out.add(u16(tb, 0))
        elif code in SHAPES:
            out |= shape_bitmaps(code, b)
        elif code == 37:
            p = skip_rect(b, 2)
            flags = u16(b, p)
            if flags & 0x0001:  # HasFont
                out.add(u16(b, p + 2))
        elif code in (7, 34):
            p = 2 + (1 if code == 34 else 0) + (2 if code == 34 else 0)
            while b[p]:
                out.add(u16(b, p + 1))
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
        name = b[10:10 + b[9]] or b[9 + 1 + b[9] + 1:].split(b'\0')[0]
        print('    external image %d -> %s' % (c, name.decode('latin-1')))
    for c in kinds.get('Imported', []):
        print('    imported %d -> %s' % (c, m.imports[c]))
    for c in sorted(set(kinds.get('Font3', []) + kinds.get('Font2', []) + kinds.get('GFxCompactedFont', []))):
        print('    font %d' % c)
    if missing:
        print('  undefined ids: %s' % missing)


if __name__ == '__main__':
    main()
