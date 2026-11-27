"""The three builder suites in one process, for the mutation command (PLAN_MUTATION_NEXT B6).

Usage: python -B -I tools/test_builder_suites.py
test_builder_formats, test_swfmerge and test_hudmovie import no SDK stubs, so they can share a process; a
process costs about 0.7 s and a surviving mutant used to start one for each. It stops at the first failure, as
the mutation command only needs to know that something failed. The default unit run keeps them in separate
processes (it shards for wall time and measures coverage per suite).
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAMES = ('test_builder_formats', 'test_swfmerge', 'test_hudmovie')


def main(names=NAMES, stream=None):
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    result = unittest.TextTestRunner(stream=stream or sys.stderr, verbosity=0, failfast=True).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
