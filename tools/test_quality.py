"""Check that quality gates reject missing, incomplete and below-threshold results."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from quality_checks import (MOD_FOLDERS, ROOT, ci_trigger_errors, coverage_errors,  # noqa: E402
                            line_ending_errors, mod_errors, mutation_errors, release_gate_errors)

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

    def test_fixtures_check_out_with_lf_on_every_runner(self):
        """Windows runners set core.autocrlf, which turned the byte-compared fixtures into CRLF (PHASE3 3bm)."""
        self.assertEqual(line_ending_errors(), [])
        self.assertEqual(line_ending_errors(['tools/fixtures/a.json: eol: lf']), [])
        self.assertEqual(line_ending_errors(['tools/fixtures/a.json: eol: unspecified']),
                         ['tools/fixtures/a.json: must check out with LF (.gitattributes eol=lf)'])

    def test_commit_hooks_lint_with_the_versions_ci_uses(self):
        """A hook with another ruff or actionlint would pass commits that CI then fails (PHASE3 3bz)."""
        from quality_checks import hook_version_errors

        hooks = ('repos:\n  - repo: https://github.com/astral-sh/ruff-pre-commit\n    rev: v0.17.2\n'
                 '  - repo: local\n    hooks:\n      - id: actionlint\n'
                 '        additional_dependencies: [actionlint-py==1.7.12.25, shellcheck-py==0.11.0.1]\n')
        requirements = 'ruff==0.17.2\ncoverage==7.17.0\n'
        ci = '          rhysd/actionlint:1.7.12 -color\n'
        self.assertEqual(hook_version_errors(hooks, requirements, ci), [])
        self.assertEqual(hook_version_errors(hooks.replace('v0.17.2', 'v0.17.6'), requirements, ci),
                         ['.pre-commit-config.yaml: ruff v0.17.6 differs from requirements-ci.txt ruff==0.17.2'])
        self.assertEqual(hook_version_errors(hooks, requirements, ci.replace('1.7.12', '1.7.13')),
                         ['.pre-commit-config.yaml: actionlint 1.7.12 differs from ci.yml rhysd/actionlint:1.7.13'])
        self.assertEqual(hook_version_errors('repos: []\n', requirements, ci),
                         ['.pre-commit-config.yaml: no ruff-pre-commit hook',
                          '.pre-commit-config.yaml: no actionlint-py hook'])
        self.assertEqual(hook_version_errors((ROOT / '.pre-commit-config.yaml').read_text(encoding='utf-8'),
                                             (ROOT / 'requirements-ci.txt').read_text(encoding='utf-8'),
                                             (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')), [])

    def test_the_secret_scan_hook_uses_the_gitleaks_version_ci_downloads(self):
        """A hook with another gitleaks has other rules, so a commit it passes could fail the CI scan."""
        from quality_checks import gitleaks_version_errors

        hooks = '  - repo: https://github.com/gitleaks/gitleaks\n    rev: v8.30.1\n    hooks:\n      - id: gitleaks\n'
        workflow = '  GITLEAKS_VERSION: 8.30.1\n'
        self.assertEqual(gitleaks_version_errors(hooks, workflow), [])
        self.assertEqual(gitleaks_version_errors(hooks.replace('v8.30.1', 'v8.31.0'), workflow),
                         ['.pre-commit-config.yaml: gitleaks v8.31.0 differs from secrets.yml GITLEAKS_VERSION 8.30.1'])
        self.assertEqual(gitleaks_version_errors(hooks, 'jobs: {}\n'),
                         ['.pre-commit-config.yaml: gitleaks v8.30.1 differs from secrets.yml GITLEAKS_VERSION ?'])
        self.assertEqual(gitleaks_version_errors('repos: []\n', workflow),
                         ['.pre-commit-config.yaml: no gitleaks hook'])
        self.assertEqual(gitleaks_version_errors(
            (ROOT / '.pre-commit-config.yaml').read_text(encoding='utf-8'),
            (ROOT / '.github/workflows/secrets.yml').read_text(encoding='utf-8')), [])

    def test_the_real_ci_triggers_are_safe(self):
        self.assertEqual(ci_trigger_errors((ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')), [])

    def test_the_real_release_workflow_is_gated(self):
        workflows = ROOT / '.github/workflows'
        self.assertEqual(release_gate_errors((workflows / 'ci.yml').read_text(encoding='utf-8'),
                                             (workflows / 'release.yml').read_text(encoding='utf-8')), [])


if __name__ == '__main__':
    unittest.main()
