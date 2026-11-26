"""Unit tests for the runtime HUD merge (PLAN_V12): swfmerge.py against synthetic, asset-free movies.

The foreign HUD here is a stand-in for another mod's replacement of the stock HUD movie: a stock-shaped
prefix, its own characters, its own gradient records. Variants break one rule each (id clash, prefix, names,
gradient accounting, manifest version) and must be refused with a message. Real-movie checks live in
test_minimap_as.py / test_minimap_mod.py.
"""
import json
import os
import struct
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'sdk_mods', 'classic_minimap'))
import swfmerge  # noqa: E402
from swfmerge import MergeRefused, tag  # noqa: E402
import as2asm  # noqa: E402
from as2asm import Fn, function  # noqa: E402
from ci_fixture import build_fixture, movie, sprite  # noqa: E402
from swfbuild import core_version  # noqa: E402

VERSION = '9.9.9'


def gradient_shape(sid):
    """DefineShape3 with one linear gradient fill and no edges."""
    body = (struct.pack('<H', sid) + b'\x00' + b'\x01' + b'\x10' + b'\x00' + b'\x01' + b'\x00\xff\x00\x00\xff'
            + b'\x00' + b'\x00' + b'\x00')
    return tag(32, body)


def solid_shape(sid):
    """DefineShape3 with one solid fill and no edges."""
    return tag(32, struct.pack('<H', sid) + b'\x00' + b'\x01' + b'\x00' + b'\xff\x00\x00\xff' + b'\x00\x00\x00')


def gradient_image(gid):
    return tag(1003, struct.pack('<H', gid) + b'img\0')


def exports(*pairs):
    return tag(56, struct.pack('<H', len(pairs)) + b''.join(struct.pack('<H', i) + n.encode() + b'\0' for i, n in pairs))


def do_action(*names):
    funcs = []
    for name in names:
        funcs.append(function(name, (), Fn().ret()))
    return tag(12, as2asm.encode(funcs, end=True))


STOCK_PREFIX = [sprite(1), gradient_shape(2), gradient_image(0), sprite(3)]
BLOCK = [sprite(100), gradient_shape(101), gradient_shape(102), exports((100, 'bl1mm_map')), do_action('MinimapCmd')]


def assemble(prefix, block_tags, version=VERSION, with_manifest=True):
    """Our movie: stock-shaped prefix, the manifest, the block, ShowFrame and End."""
    stock = movie(prefix)
    head, root, trailing = swfmerge.split(stock)
    at = swfmerge.first_show(root)
    block = b''.join(block_tags)
    manifest = swfmerge.manifest_tag(version, root[:at], block) if with_manifest else b''
    out = bytearray(head + b''.join(r for _, _, r in root[:at]) + manifest + block
                    + b''.join(r for _, _, r in root[at:]) + trailing)
    struct.pack_into('<I', out, 4, len(out))
    return bytes(out)


def foreign_movie(extra=(), prefix=None):
    """Another mod's HUD: the stock prefix, then its own characters after the first frame (as Extended UI's)."""
    head, root, trailing = swfmerge.split(movie(list(STOCK_PREFIX if prefix is None else prefix)))
    at = swfmerge.first_show(root)
    out = bytearray(head + b''.join(r for _, _, r in root[:at + 1]) + b''.join(extra)
                    + b''.join(r for _, _, r in root[at + 1:]) + trailing)
    struct.pack_into('<I', out, 4, len(out))
    return bytes(out)


class BitWriter:
    def __init__(self):
        self.bits = []

    def u(self, value, n):
        self.bits += [(value >> (n - 1 - i)) & 1 for i in range(n)]
        return self

    def s(self, value, n):
        return self.u(value & ((1 << n) - 1), n)

    def matrix(self, scale=False, rotate=False):
        self.u(int(scale), 1)
        if scale:
            self.u(5, 5).s(-3, 5).s(7, 5)
        self.u(int(rotate), 1)
        if rotate:
            self.u(5, 5).s(2, 5).s(-9, 5)
        return self.u(4, 5).s(-5, 4).s(6, 4)

    def data(self):
        bits = self.bits + [0] * (-len(self.bits) % 8)
        return bytes(sum(bit << (7 - j) for j, bit in enumerate(bits[i:i + 8])) for i in range(0, len(bits), 8))


def rich_shape(version):
    """A shape with every record kind the walker handles. Returns (code, body, expected gradients, bitmaps)."""
    code = {1: 2, 3: 32, 4: 83}[version]
    body = struct.pack('<H', 5) + b'\x00' + (b'\x00\x00' if version == 4 else b'')
    color = b'\x01\x02\x03\x04' if version >= 3 else b'\x01\x02\x03'
    # three fills: solid, scaled+rotated linear gradient (2 stops) and a clipped bitmap
    fills = b'\x00' + color
    expected = []
    if version >= 2 or True:
        stops = 2 * (5 if version >= 3 else 4)
        fills += b'\x10' + BitWriter().matrix(True, True).data() + b'\x02' + bytes(stops)
        expected.append(0x10)
    fills += b'\x41' + struct.pack('<H', 7) + BitWriter().matrix().data()
    body += b'\x03' + fills
    if version == 4:
        # line 1: miter join, filled with a radial gradient; line 2: plain colour
        body += b'\x02' + struct.pack('<H', 20) + bytes([0x28 | 0x00, 0]) + b'\x00\x00' + b'\x12' \
            + BitWriter().matrix().data() + b'\x01' + bytes(5)
        expected.append(0x12)
        body += struct.pack('<H', 20) + bytes([0, 0]) + color
    else:
        body += b'\x01' + struct.pack('<H', 20) + color
    w = BitWriter().u(2, 4).u(1, 4)                        # fill indexes use 2 bits, line indexes 1
    w.u(0, 1).u(15, 5).u(4, 5).s(10, 4).s(-3, 4).u(1, 2).u(2, 2).u(1, 1)       # move + fill0 + fill1 + line
    w.u(1, 1).u(1, 1).u(4, 4).u(1, 1).s(3, 6).s(-4, 6)                          # general straight line
    w.u(1, 1).u(1, 1).u(4, 4).u(0, 1).u(1, 1).s(5, 6)                           # vertical line
    w.u(1, 1).u(1, 1).u(4, 4).u(0, 1).u(0, 1).s(-5, 6)                          # horizontal line
    w.u(1, 1).u(0, 1).u(3, 4).s(1, 5).s(2, 5).s(-3, 5).s(4, 5)                  # curve
    w.u(0, 1).u(2 | 4, 5).u(0, 2).u(3, 2)                                       # fill0 / fill1 change only
    w.u(0, 1).u(8, 5).u(1, 1)                                                   # line style change only
    w.u(0, 1).u(16, 5)                                                          # new styles: align, then tables
    head = w.data()
    new_fills = b'\x01' + b'\x13' + BitWriter().matrix().data() + b'\x01' + bytes(5 if version >= 3 else 4) + b'\x00\x00'
    if version < 3:
        new_fills = b'\x01\x00' + color
    else:
        expected.append(0x13)
    new_lines = b'\x00'
    tail = BitWriter().u(1, 4).u(0, 4).u(0, 6).data()                           # nf=1, nl=0, end record
    body += head + new_fills + new_lines + tail
    return code, body, expected, {7}


class ShapeWalkerTests(unittest.TestCase):
    def test_every_record_kind_is_walked(self):
        for version in (1, 3, 4):
            code, body, gradients, bitmaps = rich_shape(version)
            self.assertEqual(swfmerge.walk_shape(code, body), (bitmaps, gradients), version)
            self.assertEqual(swfmerge.shape_gradient_count(code, body), len(gradients))

    def test_non_shapes_have_no_gradients(self):
        self.assertEqual(swfmerge.shape_gradient_count(39, b'\x00\x00\x01\x00'), 0)

    def test_unknown_fill_type_is_an_error(self):
        body = struct.pack('<H', 5) + b'\x00' + b'\x01\x77' + b'\x00' + b'\x00\x00\x00'
        with self.assertRaises(ValueError):
            swfmerge.walk_shape(32, body)

    def test_wide_style_counts(self):
        body = struct.pack('<H', 5) + b'\x00' + b'\xff' + struct.pack('<H', 1) + b'\x00\x01\x02\x03\x04'
        body += b'\xff' + struct.pack('<H', 0) + b'\x00' + b'\x00\x00'
        self.assertEqual(swfmerge.walk_shape(32, body), (set(), []))

    def test_signed_bits(self):
        br = swfmerge.Bits(bytes([0b10110000]))
        self.assertEqual((br.s(3), br.s(1), br.s(0)), (-3, -1, 0))
        self.assertEqual(br.align(), 1)

    def test_fields_read_across_byte_boundaries(self):
        """Fields of any width, from any bit offset, in order (the reader takes whole fields, PHASE3 3bo)."""
        widths = [0, 1, 3, 5, 7, 8, 9, 13, 16, 17, 31, 2, 33, 4]
        values = [(0x5A5A5A5A5 * (i + 3)) & ((1 << n) - 1) for i, n in enumerate(widths)]
        w = BitWriter()
        for value, n in zip(values, widths):
            w.u(value, n)
        br = swfmerge.Bits(b'\xee' + w.data(), 1)
        self.assertEqual([br.u(n) for n in widths], values)
        self.assertEqual(br.p, 8 + sum(widths))

    def test_reading_past_the_end_is_an_error(self):
        """A truncated shape must fail (IndexError), so merge() refuses it instead of reading zeros."""
        br = swfmerge.Bits(b'\xff\xff', 1)
        self.assertEqual(br.u(4), 15)
        with self.assertRaises(IndexError):
            br.u(5)


class ManifestTests(unittest.TestCase):
    def test_describes_the_block(self):
        ours = assemble(STOCK_PREFIX, BLOCK)
        info, block = swfmerge.read_block(ours)
        self.assertEqual(info['version'], VERSION)
        self.assertEqual(info['prefix_codes'], [39, 32, 1003, 39])
        self.assertEqual(info['gradients_before'], 1)
        self.assertEqual(info['gradients'], 2)
        self.assertEqual(info['characters'], [100, 101, 102])
        self.assertEqual(info['exports'], ['bl1mm_map'])
        self.assertEqual(info['functions'], ['MinimapCmd'])
        self.assertEqual(block, b''.join(BLOCK))

    def test_movie_without_manifest_is_refused(self):
        with self.assertRaisesRegex(MergeRefused, 'no block manifest'):
            swfmerge.merge(foreign_movie(), assemble(STOCK_PREFIX, BLOCK, with_manifest=False), VERSION)

    def test_truncated_block_is_refused(self):
        ours = assemble(STOCK_PREFIX, BLOCK)
        _, root, _ = swfmerge.split(ours)
        cut = ours[:ours.index(b''.join(BLOCK))] + BLOCK[0]
        cut = bytearray(cut + tag(1, b'') + tag(0, b''))
        struct.pack_into('<I', cut, 4, len(cut))
        with self.assertRaisesRegex(MergeRefused, 'does not match'):
            swfmerge.read_block(bytes(cut))
        self.assertTrue(root)

    def test_real_build_carries_a_manifest_for_its_version(self):
        info, block = swfmerge.read_block(build_fixture())
        self.assertEqual(info['version'], core_version())
        self.assertEqual(info['tags'], len(swfmerge.read_tags(block, 0, len(block))))
        self.assertIn('bl1mm_map', info['exports'])
        self.assertIn('MinimapCmd', info['functions'])

    def test_function_names_skips_nested_and_handles_both_encodings(self):
        a = Fn().ret()
        body = as2asm.encode([function('Outer', ('a', 'b'), a)], end=True)
        self.assertEqual(swfmerge.function_names(body), ['Outer'])
        # DefineFunction2: name, 1 param (register 0, name), 0 registers, flags 0, code size 0
        rec = b'F2\0' + struct.pack('<H', 1) + b'\x01' + struct.pack('<H', 0) + b'\x00p\0' + struct.pack('<H', 0)
        f2 = struct.pack('<BH', 0x8E, len(rec)) + rec
        self.assertEqual(swfmerge.function_names(f2 + b'\x00'), ['F2'])
        # DefineFunction with an anonymous function: no name reported
        rec = b'\0' + struct.pack('<H', 0) + struct.pack('<H', 0)
        self.assertEqual(swfmerge.function_names(struct.pack('<BH', 0x9B, len(rec)) + rec + b'\x00'), [])


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.ours = assemble(STOCK_PREFIX, BLOCK)

    def merged(self, foreign):
        return swfmerge.merge(foreign, self.ours, VERSION)

    def test_block_lands_before_the_first_frame_with_foreign_content_kept(self):
        extra = [sprite(500), sprite(501)]
        out = self.merged(foreign_movie(extra))
        head, root, _ = swfmerge.split(out)
        codes = [c for c, _, _ in root]
        self.assertEqual(struct.unpack_from('<I', out, 4)[0], len(out))
        at = swfmerge.first_show(root)
        raws = [r for _, _, r in root]
        self.assertEqual(b''.join(raws[len(STOCK_PREFIX):at]), b''.join(BLOCK))
        self.assertEqual(codes[at:at + 2], [1, 39])
        ids = swfmerge.defined_ids(root)
        for want in (500, 501, 100, 101, 102):
            self.assertIn(want, ids)
        self.assertNotIn(swfmerge.METADATA, codes)

    def test_foreign_gradient_records_after_the_block_move_up(self):
        # the foreign movie has a second gradient fill after the shared prefix; its image record is id 1
        foreign = foreign_movie([gradient_shape(500), gradient_image(1)])
        out = self.merged(foreign)
        _, root, _ = swfmerge.split(out)
        records = [struct.unpack_from('<H', b, 0)[0] for c, b, _ in root if c == 1003]
        self.assertEqual(records, [0, 3])          # id 0 stays; id 1 moves up by the block's 2 fills

    def test_rest_of_the_foreign_movie_is_untouched(self):
        foreign = foreign_movie([sprite(500)])
        out = self.merged(foreign)
        self.assertTrue(out.endswith(sprite(500) + tag(0, b'')))
        self.assertEqual(out[:4] + out[8:12], foreign[:4] + foreign[8:12])

    def test_merge_is_deterministic(self):
        foreign = foreign_movie([sprite(500)])
        self.assertEqual(self.merged(foreign), self.merged(foreign))

    def test_character_id_clash_is_refused(self):
        with self.assertRaisesRegex(MergeRefused, 'character id clash at 101'):
            self.merged(foreign_movie([sprite(101)]))

    def test_prefix_mismatch_is_refused(self):
        with self.assertRaisesRegex(MergeRefused, 'differs from the stock'):
            self.merged(foreign_movie(prefix=STOCK_PREFIX[:3]))

    def test_export_name_clash_is_refused(self):
        with self.assertRaisesRegex(MergeRefused, 'export name clash: bl1mm_map'):
            self.merged(foreign_movie([sprite(500), exports((500, 'bl1mm_map'))]))

    def test_function_name_clash_is_refused(self):
        with self.assertRaisesRegex(MergeRefused, 'function name clash: MinimapCmd'):
            self.merged(foreign_movie([do_action('Other', 'MinimapCmd')]))

    def test_other_names_are_fine(self):
        self.merged(foreign_movie([exports((500, 'theirs')), do_action('Theirs')]))

    def test_gradient_fills_before_the_block_must_match(self):
        with self.assertRaisesRegex(MergeRefused, "gradient fills don't add up"):
            self.merged(foreign_movie(prefix=[sprite(1), solid_shape(2), gradient_image(0), sprite(3)]))

    def test_gradient_image_without_a_fill_is_refused(self):
        with self.assertRaisesRegex(MergeRefused, "gradient fills don't add up.*highest image record 5"):
            self.merged(foreign_movie([gradient_image(5)]))

    def test_manifest_version_mismatch_is_refused(self):
        with self.assertRaisesRegex(MergeRefused, 'built for mod .*use Rebuild HUD movie'):
            swfmerge.merge(foreign_movie(), self.ours, '1.0.0')

    def test_compressed_movie_is_refused(self):
        with self.assertRaisesRegex(MergeRefused, 'unsupported movie signature'):
            self.merged(b'CWS' + foreign_movie()[3:])

    def test_movie_without_a_frame_is_refused(self):
        bad = bytearray(b'FWS\x08' + struct.pack('<I', 0) + b'\x08\x00\x00\x18\x01\x00' + tag(0, b''))
        struct.pack_into('<I', bad, 4, len(bad))
        with self.assertRaisesRegex(MergeRefused, 'no ShowFrame'):
            self.merged(bytes(bad))

    def test_truncated_movie_is_refused(self):
        with self.assertRaisesRegex(MergeRefused, 'truncated|unreadable'):
            self.merged(foreign_movie([sprite(500)])[:-5])

    def test_garbage_shape_is_refused(self):
        with self.assertRaisesRegex(MergeRefused, 'unreadable movie'):
            self.merged(foreign_movie(prefix=STOCK_PREFIX, extra=[tag(32, b'\x01\x00\x00')]))

    def test_manifest_json_is_plain_data(self):
        info, _ = swfmerge.read_block(self.ours)
        self.assertEqual(json.loads(json.dumps(info)), info)


if __name__ == '__main__':
    unittest.main()
