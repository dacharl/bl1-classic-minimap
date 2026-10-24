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
