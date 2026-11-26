"""Run unit tests in separate Python processes (default: --workers auto).

The default run uses one process per suite; explicit test IDs get one per case.
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

DEFAULT_TESTS = ['test_ci.SourceChecks', 'test_quality.GateChecks', 'test_runners.RunnerChecks', 'test_profiler',
                 'test_land.LandChecks', 'test_workflow.WorkflowChecks', 'test_swfmerge', 'test_hudmovie']
# These cases run the real mod's main(), which works only once per process.
PER_CASE = ['test_ci.SourceChecks']
# Seconds per process: far above the slowest suite (about 30 s locally), far below CI's 10-minute job limit, so a
# hang fails with its output instead of the job being cancelled with none (PHASE3 3bp).
DEFAULT_TIMEOUT = 240


def test_ids(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from test_ids(test)
        else:
            yield test.id()


def case_ids(names):
    return list(test_ids(unittest.defaultTestLoader.loadTestsFromNames(names)))


def process_jobs(suites, per_case=PER_CASE):
    jobs = []
    for suite in suites:
        jobs += case_ids([suite]) if suite in per_case else [suite]
    return jobs


def text(output):
    return output.decode(errors='replace') if isinstance(output, bytes) else output or ''


def run_case(name, coverage, timeout=None):
    command = [sys.executable, '-B', '-I']
    if coverage:
        command += ['-m', 'coverage', 'run', '--parallel-mode']
    command += [str(Path(__file__).resolve()), '--case', name]
    try:
        return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as expired:   # killed; on POSIX run() no longer waits for its pipes
        return subprocess.CompletedProcess(command, 1, text(expired.stdout),
                                           text(expired.stderr) + f'\n{name}: timed out after {timeout:g} s\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', default='auto', help='auto (available CPUs) or a positive integer')
    parser.add_argument('--coverage', action='store_true')
    parser.add_argument('--timeout', type=float, default=DEFAULT_TIMEOUT, help='seconds per test process')
    parser.add_argument('--case', help=argparse.SUPPRESS)
    parser.add_argument('tests', nargs='*', help='optional unittest test IDs')
    args = parser.parse_args()
    if args.case:
        result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromName(args.case))
        return 0 if result.wasSuccessful() else 1
    names = case_ids(args.tests) if args.tests else process_jobs(DEFAULT_TESTS)
    try:
        workers = worker_count(args.workers, tasks=len(names))
    except ValueError as error:
        parser.error(str(error))
    if args.coverage:
        (ROOT / 'dist/ci').mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, '-I', '-m', 'coverage', 'erase'], cwd=ROOT, check=True)
    cases = unittest.defaultTestLoader.loadTestsFromNames(names).countTestCases()
    print(f'Running {cases} unit tests in {len(names)} processes using {workers} workers ({args.workers})', flush=True)
    failed = False
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_case, name, args.coverage, args.timeout): name for name in names}
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
