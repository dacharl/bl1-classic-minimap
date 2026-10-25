"""Run unit tests in separate Python processes (default: --workers auto).

Use --coverage to merge branch coverage from every child before applying gates.
Mutation workers use test_ci.py directly so they do not start nested pools.
"""
import argparse
import concurrent.futures
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from parallel_workers import worker_count  # noqa: E402

DEFAULT_TESTS = ['test_ci.SourceChecks', 'test_quality.GateChecks', 'test_runners.RunnerChecks', 'test_profiler']


def test_ids(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from test_ids(test)
        else:
            yield test.id()


def run_case(name, coverage):
    command = [sys.executable, '-B', '-I']
    if coverage:
        command += ['-m', 'coverage', 'run', '--parallel-mode']
    command += [str(Path(__file__).resolve()), '--case', name]
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', default='auto', help='auto (available CPUs) or a positive integer')
    parser.add_argument('--coverage', action='store_true')
    parser.add_argument('--case', help=argparse.SUPPRESS)
    parser.add_argument('tests', nargs='*', help='optional unittest test IDs')
    args = parser.parse_args()
    if args.case:
        result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromName(args.case))
        return 0 if result.wasSuccessful() else 1
    names = list(test_ids(unittest.defaultTestLoader.loadTestsFromNames(args.tests or DEFAULT_TESTS)))
    try:
        workers = worker_count(args.workers, tasks=len(names))
    except ValueError as error:
        parser.error(str(error))
    if args.coverage:
        (ROOT / 'dist/ci').mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, '-I', '-m', 'coverage', 'erase'], cwd=ROOT, check=True)
    print(f'Running {len(names)} unit tests using {workers} workers ({args.workers})', flush=True)
    failed = False
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_case, name, args.coverage): name for name in names}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            print(f'{futures[future]}: {"FAIL" if result.returncode else "PASS"}', flush=True)
            if result.returncode:
                failed = True
                print(result.stdout + result.stderr, flush=True)
    if args.coverage:
        subprocess.run([sys.executable, '-I', '-m', 'coverage', 'combine'], cwd=ROOT, check=True)
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
