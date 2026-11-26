"""Run the unit tests with combined branch coverage and enforce the per-file floors, as the CI test job does.

The pre-push hook runs this (.pre-commit-config.yaml), so a coverage failure shows up before the push, not in CI.
Usage: python -I tools/check_coverage.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STEPS = (
    ('unit tests with branch coverage', ['tools/run_tests.py', '--coverage']),
    ('coverage report', ['-m', 'coverage', 'report']),
    ('coverage json', ['-m', 'coverage', 'json', '-q']),
    ('per-file floors', ['tools/quality_checks.py', 'coverage']),
)


def main():
    for name, args in STEPS:
        print(f'== {name}', flush=True)
        if subprocess.run([sys.executable, '-B', '-I', *args], cwd=ROOT).returncode:
            print(f'check_coverage: {name} failed', file=sys.stderr)
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
