"""SWF/GFx record primitives shared by the movie builder and the runtime merge (PLAN_BUILDER_SPLIT).

Reading: little-endian fields (`u16`, `u32`), tag headers in the short and the long form (`header`), the tag list
of a body (`read_tags`), a root timeline (`top_level`), a RECT's end (`skip_rect`). Writing: tag framing (`tag`),
16-bit words, PlaceObject2 (`place`), DefineSprite (`sprite`, `one_frame_sprite`), MATRIX and RECT bytes and the
MSB-first `BitWriter` the shape records are built with. Pure Python on bytes, with no game imports, so the offline
suites exercise the code that runs in game.
"""
import struct

LONG_FORM = 0x3F        # a tag header's 6-bit length field: "a 32-bit length follows"

# SWF tag codes used by the builder, and the PlaceObject2 flag bits (SWF file format specification)
DO_ACTION, SHOW_FRAME_CODE, END_CODE = 12, 1, 0
PLACE_OBJECT2, REMOVE_OBJECT2, FRAME_LABEL = 26, 28, 43
DEFINE_SHAPE3, DEFINE_EDIT_TEXT, DEFINE_SPRITE, DEFINE_FONT3, EXPORT_ASSETS = 32, 37, 39, 75, 56
HAS_CHARACTER, HAS_MATRIX, HAS_NAME, HAS_CLIP_DEPTH = 0x02, 0x04, 0x20, 0x40
TWIPS = 20                        # twips per pixel


def u16(d, p=0):
    """Unsigned little-endian 16-bit field at offset p."""
    return struct.unpack_from("<H", d, p)[0]


def u32(d, p=0):
    """Unsigned little-endian 32-bit field at offset p."""
    return struct.unpack_from("<I", d, p)[0]


def words(*values):
    """The values as consecutive unsigned little-endian 16-bit fields."""
    return struct.pack("<%dH" % len(values), *values)


def header(d, p):
    """(code, body length, body offset) of the tag whose header starts at p, in the short or the long form."""
    head = u16(d, p)
    p += 2
    code, ln = head >> 6, head & LONG_FORM
    if ln == LONG_FORM:
        ln = u32(d, p)
        p += 4
    return code, ln, p


def tag(code, body):
    if len(body) < 0x3F and code not in (6, 21, 35, 20, 36, 90):
        return words((code << 6) | len(body)) + body
    return words((code << 6) | LONG_FORM) + struct.pack("<I", len(body)) + body


def read_tags(d, p, end):
    out = []
    while p < end:
        code, ln, p = header(d, p)
        out.append((code, d[p:p + ln]))
        p += ln
        if code == 0:
            break
    return out


def skip_rect(b, p):
    return p + (5 + 4 * (b[p] >> 3) + 7) // 8


SHOW_FRAME, END = tag(SHOW_FRAME_CODE, b''), tag(END_CODE, b'')


def top_level(d):
    """[(code, body, raw_bytes)] for the root timeline."""
    p = skip_rect(d, 8) + 4
    out = []
    while p < len(d):
        start = p
        code, ln, p = header(d, p)
        out.append((code, d[p:p + ln], d[start:p + ln])); p += ln
        if code == END_CODE:
            break
    return out


def twips(pixels):
    return int(round(pixels * TWIPS))


def place(depth, character, matrix=None, name=None, clip_depth=None):
    """PlaceObject2 of `character` at `depth`; the optional matrix (bytes), instance name and clip depth follow
    in the file's field order, each with its flag bit."""
    flags = (HAS_CHARACTER | (HAS_MATRIX if matrix else 0) | (HAS_NAME if name else 0)
             | (HAS_CLIP_DEPTH if clip_depth is not None else 0))
    body = bytes([flags]) + words(depth, character) + (matrix or b'')
    body += name.encode() + b'\0' if name else b''
    body += words(clip_depth) if clip_depth is not None else b''
    return tag(PLACE_OBJECT2, body)


def sprite(sid, frames, *tags):
    """DefineSprite: id, frame count, the control tags, End."""
    return tag(DEFINE_SPRITE, words(sid, frames) + b''.join(tags) + END)


def one_frame_sprite(sid, *tags):
    return sprite(sid, 1, *tags, SHOW_FRAME)


def translate_matrix(tx, ty):
    """SWF MATRIX with only a translation (pixels)."""
    a, b = twips(tx), twips(ty)
    n = max(a.bit_length(), b.bit_length(), (-a).bit_length(), (-b).bit_length()) + 1
    bits = '0' + '0' + format(n, '05b') + format(sb(a, n), '0%db' % n) + format(sb(b, n), '0%db' % n)
    bits += '0' * (-len(bits) % 8)
    return int(bits, 2).to_bytes(len(bits) // 8, 'big')


def sb(v, nbits):
    return v & ((1 << nbits) - 1)


def raw_id(raw):
    """Character id of a raw definition tag (header short or long form)."""
    return u16(raw, header(raw, 0)[2])


class BitWriter:
    """MSB-first bit packing for SWF records (RECT, shape records)."""

    def __init__(self):
        self.bits = []

    def u(self, v, n):
        self.bits += [(v >> (n - 1 - i)) & 1 for i in range(n)]

    def s(self, v, n):
        self.u(v & ((1 << n) - 1), n)

    def data(self):
        bits = self.bits + [0] * (-len(self.bits) % 8)
        return bytes(int(''.join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8))

    def style_change(self, move, fill0=None, fill1=None, line=None):
        """StyleChangeRecord (no new styles) that moves to `move` (twips) and selects the given style indices
        (None leaves a style alone). Style indices are 1 bit wide here: NumFillBits and NumLineBits are at most 1."""
        self.u(0, 1)                                    # not an edge record
        self.u(0, 1)                                    # StateNewStyles
        for index in (line, fill1, fill0):              # StateLineStyle, StateFillStyle1, StateFillStyle0
            self.u(int(index is not None), 1)
        self.u(1, 1)                                    # StateMoveTo
        n = signed_bits(*move)
        self.u(n, 5); self.s(move[0], n); self.s(move[1], n)
        for index in (fill0, fill1, line):              # in the order the specification stores them
            if index is not None:
                self.u(index, 1)

    def line_to(self, dx, dy):
        """StraightEdgeRecord, general line, with the fewest bits (at least 2) that hold both deltas."""
        n = max(2, signed_bits(dx, dy))
        self.u(1, 1); self.u(1, 1); self.u(n - 2, 4)    # edge record, straight, NumBits - 2
        self.u(1, 1); self.s(dx, n); self.s(dy, n)      # general line

    def closed_path(self, points):
        """Straight edges through the points (twips) and back to the first."""
        for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1]):
            self.line_to(bx - ax, by - ay)

    def end(self):
        """EndShapeRecord."""
        self.u(0, 6)


def signed_bits(*values):
    return max([1] + [int(v).bit_length() + 1 for v in values] + [int(-v).bit_length() + 1 for v in values])


def rect_bytes(x0, x1, y0, y1):
    """SWF RECT from pixel bounds."""
    v = [twips(c) for c in (x0, x1, y0, y1)]
    n = signed_bits(*v)
    w = BitWriter()
    w.u(n, 5)
    for c in v:
        w.s(c, n)
    return w.data()


def rgba(colour, alpha=0xFF):
    return struct.pack('>I', colour)[1:] + bytes([alpha])
