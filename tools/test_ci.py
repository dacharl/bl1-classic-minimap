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
    def check_movie(self, check):
        with tempfile.TemporaryDirectory() as directory:
            movie = Path(directory) / 'synthetic.gfx'
            movie.write_bytes(build_fixture())
            # Both suites retain their assertions; only the input movie is synthetic.
            with contextlib.redirect_stdout(io.StringIO()):
                check(str(movie))

    def test_movie_without_game_assets(self):
        self.check_movie(test_minimap_as.main)

    def test_mod_without_game_assets(self):
        self.check_movie(test_minimap_mod.main)

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
