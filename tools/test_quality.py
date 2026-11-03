"""Check that quality gates reject missing, incomplete and below-threshold results."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from quality_checks import (MOD_FOLDERS, ROOT, ci_trigger_errors, coverage_errors, mod_errors,  # noqa: E402
                            mutation_errors, release_gate_errors)

CI = 'on:\n  push:\n  workflow_call:\n\njobs:\n  lint:\n    runs-on: ubuntu-latest\n'
TRIGGERS = '''on:
  push:
    branches: [main]
    paths:
      - '**'
      - '!docs/**'
      - 'docs/research/PERF_REPORT_V1.md'
      - 'docs/plans/PLAN_V11_MCP_HANDOFF.md'
  pull_request:
    branches: [main]
  merge_group:

jobs:
  lint:
    runs-on: ubuntu-latest
'''
RELEASE = '''on:
  workflow_dispatch:

jobs:
  main-only:
    steps:
      - run: test "$REF" = refs/heads/main
  checks:
    needs: main-only
    uses: ./.github/workflows/ci.yml
  release:
    needs: checks
    steps:
      - run: gh release create "$TAG"
'''


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

    def test_a_release_needs_ci_on_main(self):
        self.assertEqual(release_gate_errors(CI, RELEASE), [])
        self.assertTrue(release_gate_errors(CI.replace('  workflow_call:\n', ''), RELEASE), 'CI not callable')
        self.assertTrue(release_gate_errors(CI, RELEASE.replace('    uses: ./.github/workflows/ci.yml\n', '')),
                        'no CI job')
        self.assertTrue(release_gate_errors(CI, RELEASE.replace('    needs: checks\n', '')), 'publishes without CI')
        self.assertTrue(release_gate_errors(CI, RELEASE.replace('    needs: main-only\n', '')), 'any branch')
        self.assertTrue(release_gate_errors(CI, RELEASE.replace('refs/heads/main', 'refs/heads/dev')), 'wrong branch')
        self.assertTrue(release_gate_errors(CI, RELEASE.replace('gh release create', 'echo')), 'nothing publishes')

    def test_docs_only_pushes_skip_ci_without_blocking_required_checks(self):
        """A path-filtered workflow leaves required checks pending, so only pushes may filter; docs that
        bump_version edits are inputs to the tests, so a change to them must still run CI."""
        self.assertEqual(ci_trigger_errors(TRIGGERS), [])
        for event in ('pull_request', 'merge_group'):
            filtered = TRIGGERS.replace(f'  {event}:\n', f"  {event}:\n    paths-ignore: ['docs/**']\n")
            self.assertTrue(ci_trigger_errors(filtered), event)
        self.assertTrue(ci_trigger_errors(TRIGGERS.replace("      - '!docs/**'\n", '')), 'nothing skipped')
        self.assertTrue(ci_trigger_errors(TRIGGERS.replace("      - 'docs/research/PERF_REPORT_V1.md'\n", '')),
                        'bumped doc skipped')

    def test_the_real_ci_triggers_are_safe(self):
        self.assertEqual(ci_trigger_errors((ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')), [])

    def test_the_real_release_workflow_is_gated(self):
        workflows = ROOT / '.github/workflows'
        self.assertEqual(release_gate_errors((workflows / 'ci.yml').read_text(encoding='utf-8'),
                                             (workflows / 'release.yml').read_text(encoding='utf-8')), [])


if __name__ == '__main__':
    unittest.main()
