"""Splice the minimap block into another mod's HUD movie (PLAN_V12).

Shared by the mod (runtime merge) and tools/swfbuild.py (which writes the block manifest), so the offline
suites exercise the code that runs in game. Pure Python on bytes: no game imports.

Our movie carries, right before the block, a Metadata tag (code 77) holding a JSON manifest: the mod version,
the tag codes of stock's prefix (everything before the first ShowFrame), the gradient fill counts, and the
character ids, export names and root function names the block defines. A merge checks the foreign movie
against it and refuses on any mismatch; it never guesses.
"""
import json
import struct

try:        # inside the mod package: the in-game build (PLAN_V13)
    from .swfrecords import LONG_FORM, header, read_tags, skip_rect, tag, u16, u32, words  # noqa: F401  (re-exported)
except ImportError:     # a plain module: tools/ wrappers and the offline suites put this folder on sys.path
    from swfrecords import LONG_FORM, header, read_tags, skip_rect, tag, u16, u32, words  # noqa: F401  (re-exported)

StructError = struct.error      # a plain name: Cosmic Ray's ExceptionReplacer fails on `except (…, struct.error)` (PHASE3 3cf)

METADATA = 77
MAGIC = b"bl1mm-block\0"
SHAPES = {2: 1, 22: 2, 32: 3, 83: 4}          # DefineShape tag -> version
DEFINES = {2, 22, 32, 83, 39, 6, 20, 21, 35, 36, 90, 10, 48, 75, 11, 33, 37, 7, 34, 46, 84, 14, 18,
           1001, 1003, 1005, 1008, 1009}
GRADIENT_IMAGE = 1003                          # GFx DefineExternalGradient: id = gradient fill number


class MergeRefused(Exception):
    """The foreign HUD movie can't take our block; the message says why."""


class Bits:
    def __init__(self, b, pos=0):
        self.b, self.p = b, pos * 8

    def u(self, n):
        # Whole fields at once: a bit-at-a-time loop took about 1 s of a merge into Extended UI's HUD (PHASE3 3bo).
        p = self.p
        end = p + n
        last = (end + 7) >> 3
        if last > len(self.b):
            raise IndexError("bit field past the end of the shape")
        self.p = end
        return (int.from_bytes(self.b[p >> 3:last], "big") >> ((last << 3) - end)) & ((1 << n) - 1)

    def skip(self, n):
        """Move past n bits unread; a read beyond the end still raises."""
        self.p += n

    def s(self, n):
        v = self.u(n)
        return v - (1 << n) if n and v & (1 << (n - 1)) else v

    def align(self):
        self.p = (self.p + 7) & ~7
        return self.p >> 3


def skip_matrix(br):
    if br.u(1):
        n = br.u(5)
        br.u(n)
        br.u(n)
    if br.u(1):
        n = br.u(5)
        br.u(n)
        br.u(n)
    n = br.u(5)
    br.u(n)
    br.u(n)
    br.align()


def read_fills(b, p, ver, bitmaps, gradients=None):
    n = b[p]
    p += 1
    if n == 0xFF and ver >= 2:
        n = u16(b, p)
        p += 2
    for _ in range(n):
        t = b[p]
        p += 1
        if t == 0x00:
            p += 4 if ver >= 3 else 3
        elif t in (0x10, 0x12, 0x13):
            if gradients is not None:
                gradients.append(t)
            br = Bits(b, p)
            skip_matrix(br)
            p = br.p >> 3
            k = b[p] & 0x0F
            p += 1 + k * (5 if ver >= 3 else 4)
            if t == 0x13:
                p += 2
        elif 0x40 <= t <= 0x43:
            bitmaps.add(u16(b, p))
            p += 2
            br = Bits(b, p)
            skip_matrix(br)
            p = br.p >> 3
        else:
            raise ValueError("fill type %#x" % t)
    return p


def read_lines(b, p, ver, bitmaps, gradients=None):
    n = b[p]
    p += 1
    if n == 0xFF:
        n = u16(b, p)
        p += 2
    for _ in range(n):
        if ver < 4:
            p += 2 + (4 if ver >= 3 else 3)
        else:
            p += 2
            f1 = b[p]
            p += 2
            if (f1 >> 4) & 3 == 2:  # miter join
                p += 2
            if f1 & 0x08:            # has fill
                p = read_fills(b[:p] + bytes([1]) + b[p:], p, ver, bitmaps, gradients) - 1
            else:
                p += 4
    return p


def walk_shape(code, b):
    """(bitmap ids, gradient fill types in order) of a DefineShape tag body."""
    ver = SHAPES[code]
    bitmaps, gradients = set(), []
    p = skip_rect(b, 2)
    if ver == 4:
        p = skip_rect(b, p) + 1
    p = read_fills(b, p, ver, bitmaps, gradients)
    p = read_lines(b, p, ver, bitmaps, gradients)
    br = Bits(b, p)
    nf, nl = br.u(4), br.u(4)
    while True:
        head = br.u(6)  # edge: 1, straight, 4-bit size; style change: 0, 5 flags
        if head & 0x20:
            n = (head & 0x0F) + 2
            if not head & 0x10:
                br.skip(4 * n)                  # curve: control and anchor deltas
            elif br.u(1):
                br.skip(2 * n)                  # general line: dx, dy
            else:
                br.skip(1 + n)                  # vertical flag, one delta
            continue
        flags = head
        if flags == 0:
            break
        if flags & 1:
            br.skip(2 * br.u(5))
        if flags & 2:
            br.skip(nf)
        if flags & 4:
            br.skip(nf)
        if flags & 8:
            br.skip(nl)
        if flags & 16:
            q = br.align()
            q = read_fills(b, q, ver, bitmaps, gradients)
            q = read_lines(b, q, ver, bitmaps, gradients)
            br = Bits(b, q)
            nf, nl = br.u(4), br.u(4)
    return bitmaps, gradients


def shape_gradient_count(code, b):
    """Gradient fill styles in a top-level tag (fills and line fills, initial and inline), 0 for non-shapes.

    GFx numbers gradient fills in file order and keys its external gradient images (tag 1003) by that
    number, so inserting gradient-bearing shapes shifts every later gradient (PHASE3 run 14)."""
    return len(walk_shape(code, b)[1]) if code in SHAPES else 0


def split(d):
    """(header, [(code, body, raw)] of the root timeline up to and including End, trailing bytes)."""
    if d[:3] not in (b"GFX", b"FWS"):
        raise MergeRefused("unsupported movie signature %r (compressed?)" % bytes(d[:3]))
    try:
        head_len = skip_rect(d, 8) + 4
        p, out = head_len, []
        while p < len(d):
            start = p
            code, ln, p = header(d, p)
            if p + ln > len(d):
                raise MergeRefused("truncated tag %d" % code)
            out.append((code, d[p:p + ln], d[start:p + ln]))
            p += ln
            if code == 0:
                break
    except (IndexError, StructError) as ex:
        raise MergeRefused("unreadable movie (%s)" % ex) from ex
    return d[:head_len], out, d[p:]


def first_show(root):
    for i, (code, _, _) in enumerate(root):
        if code == 1:
            return i
    raise MergeRefused("no ShowFrame on the root timeline")


def defined_ids(root):
    return [u16(body, 0) for code, body, _ in root if code in DEFINES and len(body) >= 2]


def export_names(root):
    names = []
    for code, body, _ in root:
        if code == 56:
            n = u16(body, 0)
            q = 2
            for _ in range(n):
                q += 2
                j = body.index(b"\0", q)
                names.append(body[q:j].decode("latin-1"))
                q = j + 1
    return names


def function_names(body):
    """Names of the functions a DoAction body defines at its top level (DefineFunction / DefineFunction2)."""
    names, p = [], 0
    while p < len(body):
        c = body[p]
        p += 1
        if c == 0:
            break
        if c < 0x80:
            continue
        n = u16(body, p)
        p += 2
        if c in (0x9B, 0x8E):
            rec = body[p:p + n]
            j = rec.index(b"\0")
            name = rec[:j].decode("latin-1")
            q = j + 1
            count = u16(rec, q)
            q += 2
            if c == 0x8E:
                q += 3
                for _ in range(count):
                    q = rec.index(b"\0", q + 1) + 1
            else:
                for _ in range(count):
                    q = rec.index(b"\0", q) + 1
            if name:
                names.append(name)
            p += n + u16(rec, q)
            continue
        p += n
    return names


def root_function_names(root):
    return [name for code, body, _ in root if code == 12 for name in function_names(body)]


def gradient_total(root):
    return sum(shape_gradient_count(c, b) for c, b, _ in root)


def describe_block(added):
    """What a block of top-level tags (no End tag) defines, for the manifest."""
    root = [(c, b, b"") for c, b in read_tags(added, 0, len(added))]
    return dict(tags=len(root), gradients=gradient_total(root), characters=sorted(defined_ids(root)),
                exports=export_names(root), functions=root_function_names(root))


def manifest_tag(version, prefix, block):
    """The Metadata tag that precedes the block in our movie. `prefix` is stock's root up to its first ShowFrame."""
    info = describe_block(block)
    info.update(version=version, prefix_codes=[c for c, _, _ in prefix],
                gradients_before=gradient_total(prefix))
    return tag(METADATA, MAGIC + json.dumps(info, sort_keys=True).encode())


def read_block(ours):
    """(manifest, block bytes) from our movie; MergeRefused if it carries none."""
    _, root, _ = split(ours)
    for i, (code, body, _) in enumerate(root):
        if code == METADATA and body.startswith(MAGIC):
            info = json.loads(body[len(MAGIC):].decode())
            block = root[i + 1:i + 1 + info["tags"]]
            if len(block) != info["tags"]:
                raise MergeRefused("block manifest does not match the minimap movie")
            return info, b"".join(raw for _, _, raw in block)
    raise MergeRefused("the minimap movie has no block manifest: use Rebuild HUD movie from game files")


def shift_gradients(root, before, count):
    """Move the external gradient image records numbered at or after `before` up by `count`."""
    out = []
    for code, body, raw in root:
        if code == GRADIENT_IMAGE and count and u16(body, 0) >= before:
            body = struct.pack("<H", u16(body, 0) + count) + body[2:]
            raw = tag(code, body)
        out.append((code, body, raw))
    return out


def check_foreign(root, insert_at, info):
    """Raise MergeRefused unless `info`'s block fits into `root` (the foreign movie's root tags)."""
    codes = [c for c, _, _ in root[:insert_at]]
    if codes != info["prefix_codes"]:
        raise MergeRefused("its start differs from the stock HUD's (%d tags before the first frame, expected %d)"
                           % (len(codes), len(info["prefix_codes"])))
    clash = sorted(set(defined_ids(root)) & set(info["characters"]))
    if clash:
        raise MergeRefused("character id clash at %d" % clash[0])
    names = sorted(set(export_names(root)) & set(info["exports"]))
    if names:
        raise MergeRefused("export name clash: %s" % names[0])
    names = sorted(set(root_function_names(root)) & set(info["functions"]))
    if names:
        raise MergeRefused("root function name clash: %s" % names[0])
    before = gradient_total(root[:insert_at])
    total = gradient_total(root)
    records = [u16(b, 0) for c, b, _ in root if c == GRADIENT_IMAGE]
    if before != info["gradients_before"] or any(r >= total for r in records):
        raise MergeRefused("gradient fills don't add up (%d before the block, expected %d; %d in all, "
                           "highest image record %d)" % (before, info["gradients_before"], total,
                                                         max(records, default=-1)))


def merge(foreign, ours, version):
    """Our block spliced into `foreign` (a HUD movie's bytes), using the manifest in `ours`."""
    info, block = read_block(ours)
    if info["version"] != version:
        raise MergeRefused("the minimap's HUD movie was built for mod %s, not %s: use Rebuild HUD movie from game files"
                           % (info["version"], version))
    head, root, trailing = split(foreign)
    try:
        insert_at = first_show(root)
        check_foreign(root, insert_at, info)
    except (IndexError, StructError, ValueError) as ex:
        raise MergeRefused("unreadable movie (%s: %s)" % (type(ex).__name__, ex)) from ex
    root = shift_gradients(root, info["gradients_before"], info["gradients"])
    out = bytearray(head + b"".join(r for _, _, r in root[:insert_at]) + block
                    + b"".join(r for _, _, r in root[insert_at:]) + trailing)
    struct.pack_into("<I", out, 4, len(out))
    return bytes(out)
