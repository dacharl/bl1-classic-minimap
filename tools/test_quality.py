"""Check that quality gates reject missing, incomplete and below-threshold results."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from quality_checks import MOD_FOLDERS, ROOT, coverage_errors, mod_errors, mutation_errors  # noqa: E402


class GateChecks(unittest.TestCase):
    def test_coverage_uses_separate_line_and_branch_floors(self):
        report = {'files': {'mod.py': {'summary': {
            'num_statements': 10, 'covered_lines': 9,
            'num_branches': 10, 'covered_branches': 7,
        }}}}
        floors = {'mod.py': {'line': 90, 'branch': 70}}
        self.assertEqual(coverage_errors(report, floors), [])
        floors['mod.py']['branch'] = 71
        self.assertTrue(coverage_errors(report, floors))
        self.assertTrue(coverage_errors({'files': {}}, floors))

    def test_mutations_fail_closed_and_count_timeouts_as_undetected(self):
        report = {'mod.py': {'total': 10, 'killed': 8, 'survived': 1,
                             'timeout': 1, 'error': 0, 'pending': 0}}
        self.assertEqual(mutation_errors(report, {'mod.py': 80}), [])
        self.assertTrue(mutation_errors(report, {'mod.py': 81}))
        report['mod.py']['error'] = 1
        self.assertTrue(mutation_errors(report, {'mod.py': 0}))
        self.assertTrue(mutation_errors({}, {'mod.py': 0}))
        for result in ({'total': 0}, {'total': 1, 'pending': 1},
                       {'total': 2, 'killed': 1}):
            self.assertTrue(mutation_errors({'mod.py': result}, {'mod.py': 0}))

    def test_every_shipped_mod_is_gated(self):
        self.assertEqual(MOD_FOLDERS, ('sdk_mods/classic_minimap', 'sdk_mods/classic_minimap_profiler'))
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'sdk_mods' / 'sample'
            source.mkdir(parents=True)
            (source / 'pyproject.toml').write_text('[project]\nversion = "1.0.0"\n')
            (source / '__init__.py').write_text('__version__ = "1.0.0"\n')
            (source / 'engine.py').write_text('x = 1\n')
            gated = {'coverage': {'sdk_mods/sample/__init__.py': {}}, 'mutation': {}}
            errors = mod_errors(source, Path(directory), gated)
            self.assertIn('sdk_mods/sample/engine.py: missing coverage threshold', errors)
            self.assertIn('sdk_mods/sample/__init__.py: missing mutation threshold', errors)
            self.assertNotIn('sample: mod version fields do not match', errors)
            (source / '__init__.py').write_text('__version__ = "1.0.1"\n')
            self.assertIn('sample: mod version fields do not match', mod_errors(source, Path(directory), gated))
            # a version re-exported from a submodule counts when it is a plain name the module defines
            (source / '__init__.py').write_text('from .engine import VERSION as __version__\n')
            (source / 'engine.py').write_text('VERSION = "1.0.0"\n')
            self.assertNotIn('sample: mod version fields do not match', mod_errors(source, Path(directory), gated))

    def test_real_mods_pass_the_repository_gate(self):
        import tomllib
        quality = tomllib.loads((ROOT / 'pyproject.toml').read_text())['tool']['quality']
        for folder in MOD_FOLDERS:
            self.assertEqual(mod_errors(ROOT / folder, ROOT, quality), [], folder)


if __name__ == '__main__':
    unittest.main()
