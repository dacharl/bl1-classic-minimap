"""Run unit tests in separate Python processes (default: --workers auto).

The default run uses one process per suite; explicit test IDs get one per case.
Use --coverage to merge branch coverage from every child before applying gates.
Mutation workers use test_ci.py directly so they do not start nested pools.
"""
import argparse
import concurrent.futures
import re
import subprocess
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from parallel_workers import worker_count  # noqa: E402

# Slowest first, so the short processes fill the gaps instead of the long ones running last (PHASE3 3by).
DEFAULT_TESTS = ['test_runners.RunnerChecks', 'test_land.LandChecks', 'test_workflow.WorkflowChecks',
                 'test_ci.SourceChecks', 'test_hudmovie', 'test_profiler', 'test_swfmerge', 'test_quality.GateChecks',
                 'test_mutation_session.SessionChecks']
# These cases run the real mod's main(), which works only once per process.
PER_CASE = ['test_ci.SourceChecks']
# These suites are each one long run of independent cases, so they are split into shards ("suite#2/3" is every third
# case from the second) that run beside each other instead of setting the whole run's length (PHASE3 3cf).
SHARDS = {'test_runners.RunnerChecks': 3, 'test_land.LandChecks': 3, 'test_workflow.WorkflowChecks': 3}
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


def shard_of(job):
    """('suite', index, count) for a shard job such as 'suite#2/3'; None for any other job."""
    match = re.fullmatch(r'(.+)#(\d+)/(\d+)', job)
    return (match[1], int(match[2]), int(match[3])) if match else None


def job_cases(job):
    """The unittest IDs a job runs."""
    shard = shard_of(job)
    if not shard:
        return [job]
    suite, index, count = shard
    return case_ids([suite])[index - 1::count]


def process_jobs(suites, per_case=PER_CASE, shards=SHARDS):
    jobs = []
    for suite in suites:
        if suite in per_case:
            jobs += case_ids([suite])
        elif suite in shards:
            jobs += [f'{suite}#{index}/{shards[suite]}' for index in range(1, shards[suite] + 1)]
        else:
            jobs.append(suite)
    return jobs


def text(output):
    return output.decode(errors='replace') if isinstance(output, bytes) else output or ''


def slowest(stderr):
    """The test lines of unittest's "Slowest test durations" report, as '  1.234s  test_name'."""
    lines, inside = [], False
    for line in stderr.splitlines():
        if line.startswith('Slowest test durations'):
            inside = True
            continue
        match = re.match(r'(\d+\.\d+s)\s+(\S+)', line) if inside else None
        if match:
            lines.append(f'  {match[1]}  {match[2]}')
        elif inside and line.startswith('Ran '):
            break
    return lines


def run_case(name, coverage, timeout=None, durations=None):
    command = [sys.executable, '-B', '-I']
    if coverage:
        command += ['-m', 'coverage', 'run', '--parallel-mode']
    command += [str(Path(__file__).resolve()), '--case', name]
    if durations is not None:
        command += ['--durations', str(durations)]
    try:
        return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as expired:   # killed; on POSIX run() no longer waits for its pipes
        return subprocess.CompletedProcess(command, 1, text(expired.stdout),
                                           text(expired.stderr) + f'\n{name}: timed out after {timeout:g} s\n')


def timed(function, *args):
    start = time.monotonic()
    result = function(*args)
    return result, time.monotonic() - start


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', default='auto', help='auto (available CPUs) or a positive integer')
    parser.add_argument('--coverage', action='store_true')
    parser.add_argument('--timeout', type=float, default=DEFAULT_TIMEOUT, help='seconds per test process')
    parser.add_argument('--durations', type=int, metavar='N',
                        help="print each process's time and its N slowest tests (0: all; Python 3.12+)")
    parser.add_argument('--case', help=argparse.SUPPRESS)
    parser.add_argument('tests', nargs='*', help='optional unittest test IDs')
    args = parser.parse_args()
    if args.case:
        options = {'durations': args.durations} if args.durations is not None and sys.version_info >= (3, 12) else {}
        suite = unittest.defaultTestLoader.loadTestsFromNames(job_cases(args.case))
        result = unittest.TextTestRunner(**options).run(suite)
        return 0 if result.wasSuccessful() else 1
    names = case_ids(args.tests) if args.tests else process_jobs(DEFAULT_TESTS)
    try:
        workers = worker_count(args.workers, tasks=len(names))
    except ValueError as error:
        parser.error(str(error))
    if args.coverage:
        (ROOT / 'dist/ci').mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, '-I', '-m', 'coverage', 'erase'], cwd=ROOT, check=True)
    cases = unittest.defaultTestLoader.loadTestsFromNames([case for name in names for case in job_cases(name)]).countTestCases()
    print(f'Running {cases} unit tests in {len(names)} processes using {workers} workers ({args.workers})', flush=True)
    failed = False
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(timed, run_case, name, args.coverage, args.timeout, args.durations): name
                   for name in names}
        for future in concurrent.futures.as_completed(futures):
            result, seconds = future.result()
            status = "FAIL" if result.returncode else "PASS"
            print(f'{futures[future]}: {status}' + (f' ({seconds:.1f} s)' if args.durations is not None else ''),
                  flush=True)
            tests = slowest(result.stderr) if args.durations is not None and not result.returncode else []
            if tests:
                print('\n'.join(tests), flush=True)
            if result.returncode:
                failed = True
                print(result.stdout + result.stderr, flush=True)
    if args.coverage:
        subprocess.run([sys.executable, '-I', '-m', 'coverage', 'combine'], cwd=ROOT, check=True)
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
