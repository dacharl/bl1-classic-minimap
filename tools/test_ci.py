"""Source-only checks at the existing movie and mod test boundaries.

Usage: python -I tools/test_ci.py
"""
import contextlib
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import test_minimap_as  # noqa: E402
import test_minimap_mod  # noqa: E402
from build_sdkmod import main as package_mod  # noqa: E402
from ci_fixture import build_fixture  # noqa: E402


class SourceChecks(unittest.TestCase):
    def check_movie(self, check, original=False):
        with tempfile.TemporaryDirectory() as directory:
            movie = Path(directory) / 'synthetic.gfx'
            movie.write_bytes(build_fixture(original))
            # Both suites retain their assertions; only the input movie is synthetic.
            with contextlib.redirect_stdout(io.StringIO()):
                check(str(movie))

    def test_movie_without_game_assets(self):
        self.check_movie(test_minimap_as.main)

    def test_mod_without_game_assets(self):
        self.check_movie(test_minimap_mod.main)

    def test_original_art_movie_passes_both_suites(self):
        """Without the Enhanced movie the build uses original art (PLAN_V13 decision 2); the minimap's AS
        entry points and the mod behave exactly as with Enhanced's art."""
        self.check_movie(test_minimap_as.main, original=True)
        self.check_movie(test_minimap_mod.main, original=True)

    def test_original_art_is_glyphs_and_our_own_shapes(self):
        """Decisions 5, 12-15: the turn-in "X", new-mission "!" and north "N" are glyphs in a copy of the HUD's
        empty WillowBody font record, each over four black outline copies; the box, window and threat diamond
        are our own shapes at Enhanced's sizes. Classic's objective diamond is untouched."""
        import struct
        from swfdeps import Movie, read_tags
        from swfmerge import walk_shape
        built = build_fixture(original=True)
        movie = Movie(data=built)
        code, font = movie.defs[1318]
        self.assertEqual((code, font[5:5 + font[4]]), (75, b'WillowBody\0'))
        texts = {}
        for tid in range(1312, 1318):
            code, body = movie.defs[tid]
            self.assertEqual(code, 37)
            tail = body.split(b'\0')
            texts[tid] = (tail[-2].decode()[-1], body[-len(tail[-2]) - 3 - 4 - 9:-len(tail[-2]) - 2 - 9])
            p = 2 + (5 + 4 * (body[2] >> 3) + 7) // 8
            self.assertEqual(struct.unpack_from('<H', body, p + 2)[0], 1318)
        self.assertEqual([texts[t][0] for t in sorted(texts)], ['X', 'X', '!', '!', 'N', 'N'])
        for sid, outline in ((1301, 1312), (1303, 1314), (1305, 1316)):
            code, body = movie.defs[sid]
            placed = [struct.unpack_from('<HH', b, 1) for c, b in read_tags(body, 4, len(body)) if c == 26]
            self.assertEqual((code, placed), (39, [(1, outline), (2, outline), (3, outline), (4, outline),
                                                    (5, outline + 1)]))
        for sid in (1307, 1308, 1310):
            code, body = movie.defs[sid]
            self.assertEqual(code, 32)
            walk_shape(code, body)              # parses to the end record
        self.assertNotIn(1050, {1307, 1308, 1310})
        self.assertIn(1050, movie.defs)
        # Run 21 (PHASE3 3ak): the turn-in "X" is green like Enhanced's turn-in mark (the "!" is gold), and the box
        # is a tight frame around the window, not E shape 81's bounds (which include a transparent margin)
        import swfbuild
        self.assertIn(bytes.fromhex('66ff00ff'), movie.defs[1313][1])
        self.assertIn(bytes.fromhex('ffcc00ff'), movie.defs[1315][1])
        body = movie.defs[1307][1]
        n = body[2] >> 3
        bits = ''.join(format(x, '08b') for x in body[2:2 + (5 + 4 * n + 7) // 8])[5:]
        x0, x1, y0, y1 = (int(bits[i * n:(i + 1) * n], 2) - (1 << n if bits[i * n] == '1' else 0) for i in range(4))
        left, top = swfbuild.WINDOW_LEFT, swfbuild.WINDOW_TOP
        right, bottom = left + swfbuild.WINDOW_W, top + swfbuild.WINDOW_H
        for edge, window in ((x0, left), (y0, top)):
            self.assertTrue(-10 <= edge / 20 - window < 0, (edge / 20, window))
        for edge, window in ((x1, right), (y1, bottom)):
            self.assertTrue(0 < edge / 20 - window <= 10, (edge / 20, window))

    def test_original_art_needs_the_hud_font(self):
        from ci_fixture import fixture_inputs, movie
        from swfbuild import build
        _, status, _ = fixture_inputs()
        with self.assertRaises(SystemExit) as raised:
            build(movie([]), status, None)
        self.assertIn('no WillowBody font', str(raised.exception))

    def test_classic_gradients_keep_their_external_images(self):
        """GFx numbers gradient fills in file order and DefineExternalGradient (1003) records are keyed by that
        number. Inserting gradient-bearing shapes shifted classic's numbering, so the box took classic's bar
        textures and later classic shapes (the damage indicator) lost theirs (run 14)."""
        from ci_fixture import movie, sprite, native_contract
        from swfbuild import build, tag
        from swfdeps import read_tags, skip_rect, shape_gradient_count
        import as2asm
        import struct

        def gradient_shape(sid, count, code=2):
            # RECT(0 bits), `count` linear gradient fills (identity matrix, 2 stops), no lines, end record
            stop = (bytes([0, 255, 0, 0, 255, 255, 0, 0]) if code == 2
                    else bytes([0, 6, 182, 249, 127, 255, 6, 182, 249, 0]))
            fills = bytes([count]) + (b'\x10\x00\x02' + stop) * count
            return tag(code, struct.pack('<H', sid) + b'\x00' + fills + b'\x00' + b'\x10\x00')

        def image(gid, name):
            return tag(1003, struct.pack('<HHH', gid, 13, 256) + bytes([len(name)]) + name.encode())

        classic = movie([image(0, 'HUD_G0.tga'), image(1, 'HUD_G1.tga'), image(2, 'HUD_G2.tga'),
                         gradient_shape(10, 1), tag(1, b''), gradient_shape(11, 1), gradient_shape(12, 1)])
        status = movie([sprite(1040), sprite(1050), sprite(1066, [(1, 1050)], ['questionmark']),
                        sprite(1132, [(1, 1066)]), sprite(1154, [(1, 1040), (5, 1040), (8, 1132)]),
                        tag(12, as2asm.encode(native_contract(), end=True))])
        enhanced = movie([gradient_shape(81, 2, code=32)] +
                         [tag(2, struct.pack('<H', sid) + b'\x08\x00\x00\x00\x00\x00') for sid in (82, 108, 110, 127, 179)])
        built, _ = build(classic, status, enhanced)

        images, order, index = {}, [], 0
        for code, body in read_tags(built, skip_rect(built, 8) + 4, len(built)):
            if code == 1003:
                images[struct.unpack_from('<H', body, 0)[0]] = body[7:7 + body[6]].decode()
            n = shape_gradient_count(code, body)
            if n:
                order.append((struct.unpack_from('<H', body, 0)[0], list(range(index, index + n))))
                index += n
        mapped = {sid: [images.get(i) for i in idx] for sid, idx in order}
        self.assertEqual(mapped, {10: ['HUD_G0.tga'], 1307: [None, None], 11: ['HUD_G1.tga'], 12: ['HUD_G2.tga']})

    def test_sdkmod_archive_layout_and_cache_exclusion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'sample'
            source.mkdir()
            (source / '__init__.py').write_bytes(b'value = 42\n')
            (source / 'pyproject.toml').write_text('[project]\nversion = "1.0.0"\n')
            cache = source / '__pycache__'
            cache.mkdir()
            (cache / 'cached.pyc').write_bytes(b'not source')
            (source / 'cached.pyo').write_bytes(b'not source')
            nested = source / 'nested'
            nested.mkdir()
            (nested / 'data.txt').write_bytes(b'asset')
            with contextlib.redirect_stdout(io.StringIO()):
                package_mod(str(source), str(root / 'output'))
            with zipfile.ZipFile(root / 'output/sample.sdkmod') as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(set(archive.namelist()), {
                    'sample/__init__.py', 'sample/pyproject.toml', 'sample/nested/data.txt',
                })
                self.assertEqual(archive.read('sample/__init__.py'), b'value = 42\n')
                self.assertEqual(archive.read('sample/nested/data.txt'), b'asset')


if __name__ == '__main__':
    unittest.main()
