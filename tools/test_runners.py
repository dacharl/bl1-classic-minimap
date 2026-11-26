"""Regression checks for automatic test worker selection and runner exit status."""
import os
import concurrent.futures
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))


def kill_pid(pid):
    if sys.platform == 'win32':
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)], capture_output=True)
    else:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def process_alive(pid):
    if sys.platform == 'win32':
        out = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/NH'], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class RunnerChecks(unittest.TestCase):
    def test_auto_uses_available_cpus_and_limits_workers_to_work(self):
        from parallel_workers import worker_count

        with patch.object(os, 'process_cpu_count', return_value=8, create=True):
            self.assertEqual(worker_count('auto'), 8)
            self.assertEqual(worker_count('auto', tasks=3), 3)

    def test_worker_override_and_unavailable_cpu_count(self):
        from parallel_workers import worker_count

        with patch.object(os, 'process_cpu_count', return_value=None, create=True):
            self.assertEqual(worker_count('auto'), 1)
            self.assertEqual(worker_count('3'), 3)
        for invalid in ('0', '-1', 'invalid'):
            with self.assertRaises(ValueError):
                worker_count(invalid)

    def test_child_failure_reaches_runner_exit_status(self):
        result = subprocess.run(
            [sys.executable, '-B', '-I', str(Path(__file__).with_name('run_tests.py')),
             '--workers', '1', 'test_runners.FailingExample'],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn('intentional child failure', result.stdout + result.stderr)

    def test_mutation_worker_shuts_down_without_cleanup_tracebacks(self):
        result = subprocess.run(
            [sys.executable, '-B', '-I', str(Path(__file__).with_name('run_tests.py')),
             '--case', 'test_runners.WorkerExample.test_cleanup'],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_mutation_cli_defaults_to_auto_and_accepts_override(self):
        from run_mutations import parse_args

        with patch.object(os, 'process_cpu_count', return_value=8, create=True):
            self.assertEqual(parse_args([]).workers, 8)
            self.assertEqual(parse_args(['--workers', 'auto']).workers, 8)
            self.assertEqual(parse_args(['--workers', '2']).workers, 2)

    def test_mutation_command_kills_a_hanging_suite_and_its_children(self):
        """Cosmic Ray kills only its direct child on Windows (no killpg) and then waits for the output pipe;
        a looping grandchild held it open forever. test_mutants must end the whole tree itself."""
        import test_mutants

        with tempfile.TemporaryDirectory() as directory:
            pid_file = Path(directory) / 'pid.txt'
            child = Path(directory) / 'child.py'
            child.write_text(f'import os\nopen({str(pid_file)!r}, "w").write(str(os.getpid()))\nwhile True:\n    pass\n')
            suite = Path(directory) / 'suite.py'
            suite.write_text('import subprocess, sys\n'
                             f'subprocess.run([sys.executable, {str(child)!r}])\n')
            started = time.monotonic()
            self.assertNotEqual(test_mutants.main(suites=[str(suite)], budget=2), 0)
            self.assertLess(time.monotonic() - started, 15)
            pid = int(pid_file.read_text())
            # A surviving grandchild holds this process's output pipes, which stalled the whole runner on Linux
            # until CI cancelled it (PHASE3 3bp): kill it here so a regression fails instead of hanging.
            self.addCleanup(kill_pid, pid)
            time.sleep(0.5)
            self.assertFalse(process_alive(pid), f'grandchild {pid} survived')

    def test_posix_tree_kill_covers_every_descendant(self):
        """POSIX kill_tree must reach grandchildren (proc.kill() alone orphaned them, PHASE3 3bp): the process
        tree under a PID, from (pid, ppid) pairs as `ps -A -o pid=,ppid=` lists them."""
        import test_mutants

        table = [(1, 0), (10, 1), (11, 10), (12, 11), (13, 10), (20, 1), (21, 20), (14, 13)]
        self.assertEqual(test_mutants.process_tree(10, table), {10, 11, 12, 13, 14})
        self.assertEqual(test_mutants.process_tree(99, table), {99}, 'an unlisted root is still the tree')

    def test_suites_die_with_a_killed_mutation_command(self):
        """Cosmic Ray kills its test command the way _kill_process_group does (process group on POSIX, only
        the direct process on Windows) and then waits for the output pipe. A suite stuck in a C-level loop
        (which holds the GIL, so no in-process watchdog runs) must die with the command, or the worker
        waits forever (full mutation run stalled at 3,850/3,866)."""
        from cosmic_ray.testing import _kill_process_group

        with tempfile.TemporaryDirectory() as directory:
            pid_file = Path(directory) / 'pid.txt'
            hog = Path(directory) / 'hog.py'
            hog.write_text(f'import os\nopen({str(pid_file)!r}, "w").write(str(os.getpid()))\n'
                           'x = 10 ** (10 ** 12)\n')
            driver = Path(directory) / 'driver.py'
            driver.write_text(f'import sys\nsys.path.insert(0, {str(Path(__file__).resolve().parent)!r})\n'
                              f'import test_mutants\nraise SystemExit(test_mutants.main(suites=[{str(hog)!r}], budget=600))\n')
            proc = subprocess.Popen([sys.executable, '-B', '-I', str(driver)], stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, start_new_session=True)
            for _ in range(100):
                if pid_file.exists() and pid_file.read_text():
                    break
                time.sleep(0.1)
            pid = int(pid_file.read_text())
            _kill_process_group(proc)
            try:
                proc.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                subprocess.run(['taskkill', '/F', '/PID', str(pid)] if sys.platform == 'win32'
                               else ['kill', '-9', str(pid)], capture_output=True)
                proc.communicate()
                self.fail('the suite outlived the killed command and held its output pipe')
            time.sleep(0.5)
            self.assertFalse(process_alive(pid), f'suite {pid} survived')

    def test_watchdog_ends_a_hanging_suite_on_its_own(self):
        """With a venv, killing the launcher also kills test_mutants (job object) but not its suite, so each
        suite must stop itself at an absolute deadline."""
        runner = Path(__file__).with_name('watchdog_run.py')
        with tempfile.TemporaryDirectory() as directory:
            hang, ok, bad = (Path(directory) / n for n in ('hang.py', 'ok.py', 'bad.py'))
            hang.write_text('while True:\n    pass\n')
            ok.write_text('import sys\nprint("ran", sys.argv[0].endswith("ok.py"))\n')
            bad.write_text('raise SystemExit(7)\n')
            started = time.monotonic()
            result = subprocess.run([sys.executable, '-B', '-I', str(runner), str(time.time() + 1), str(hang)],
                                    capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertLess(time.monotonic() - started, 15)
            self.assertIn('watchdog', result.stdout + result.stderr)
            result = subprocess.run([sys.executable, '-B', '-I', str(runner), str(time.time() + 30), str(ok)],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual((result.returncode, result.stdout.strip()), (0, 'ran True'))
            result = subprocess.run([sys.executable, '-B', '-I', str(runner), str(time.time() + 30), str(bad)],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 7)

    def test_mutation_command_budget_outlasts_the_cosmic_ray_timeout(self):
        import tomllib
        import test_mutants

        config = tomllib.loads((Path(__file__).resolve().parent.parent / 'cosmic-ray.toml').read_text())
        # Cosmic Ray must time out first (recorded as a timeout); the budget then only cleans up.
        self.assertGreater(test_mutants.SUITE_BUDGET, config['cosmic-ray']['timeout'])

    def test_mutation_command_runs_each_mod_main_case_in_its_own_process(self):
        """test_ci's cases call the real mod's main(), which works once per process: the whole file in one process
        failed its baseline and no mutation run could start. Builder files are killed by test_hudmovie and
        test_swfmerge, so those must be in the command too (PHASE3 §3cc)."""
        import test_mutants

        cases = test_mutants.case_suites()
        self.assertIn('test_ci.py::SourceChecks.test_mod_without_game_assets', cases)
        self.assertIn('test_ci.py::SourceChecks.test_original_art_movie_passes_both_suites', cases)
        self.assertTrue(all(case.startswith('test_ci.py::') for case in cases))
        self.assertTrue({'test_hudmovie.py', 'test_swfmerge.py', 'test_profiler.py'} <= set(test_mutants.OTHER_SUITES))

    def test_mutation_module_filter_keeps_configured_order_and_rejects_unknowns(self):
        from run_mutations import selected_modules

        configured = ['a/core.py', 'tools/pack.py', 'b/profiler.py']
        self.assertEqual(selected_modules(configured, []), configured)
        self.assertEqual(selected_modules(configured, ['b/profiler.py', 'a/core.py']), ['a/core.py', 'b/profiler.py'])
        with self.assertRaises(SystemExit):
            selected_modules(configured, ['missing.py'])

    def test_default_run_shares_a_process_per_suite_except_cases_that_need_their_own(self):
        """A process costs about 0.5 s under coverage, which was over half of a 2-vCPU run (PHASE3 3bl)."""
        from run_tests import DEFAULT_TESTS, process_jobs

        jobs = process_jobs(['test_runners.ParallelExample', 'test_runners.FailingExample'],
                            per_case=['test_runners.ParallelExample'])
        self.assertEqual(jobs, ['test_runners.ParallelExample.test_first', 'test_runners.ParallelExample.test_second',
                                'test_runners.FailingExample'])
        jobs = process_jobs(DEFAULT_TESTS)
        self.assertNotIn('test_land.LandChecks', jobs)   # sharded instead
        self.assertIn('test_quality.GateChecks', jobs)
        self.assertNotIn('test_ci.SourceChecks', jobs)
        self.assertIn('test_ci.SourceChecks.test_original_art_movie_passes_both_suites', jobs)

    def test_default_run_starts_the_slowest_suites_first(self):
        """On the 2-vCPU Windows runner test_land (16 s), test_runners (17 s) and test_workflow (8 s) started
        after the seven short test_ci processes and ran last, one after another (PHASE3 3by)."""
        from run_tests import DEFAULT_TESTS, process_jobs, shard_of

        jobs = process_jobs(DEFAULT_TESTS)
        slow = [job for job in jobs if shard_of(job)]
        self.assertEqual(jobs[:len(slow)], slow)
        self.assertEqual({shard_of(job)[0] for job in slow},
                         {'test_runners.RunnerChecks', 'test_land.LandChecks', 'test_workflow.WorkflowChecks'})
        self.assertEqual(len(jobs), len(set(jobs)))

    def test_sharded_suites_run_every_case_exactly_once(self):
        """The three long suites are one process each no longer: they are split into shards so that no single
        process sets the length of the run (PHASE3 3cf), and a shard must not drop or repeat a case."""
        from run_tests import case_ids, job_cases, process_jobs

        suite = 'test_runners.ParallelExample'
        jobs = process_jobs([suite], shards={suite: 2})
        self.assertEqual(jobs, [f'{suite}#1/2', f'{suite}#2/2'])
        self.assertEqual(sorted(case for job in jobs for case in job_cases(job)), sorted(case_ids([suite])))
        self.assertEqual(job_cases('test_land.LandChecks.test_x'), ['test_land.LandChecks.test_x'])

    def test_durations_report_each_process_and_its_slowest_tests(self):
        """Hosted Windows test times varied from 41 to 53 s with only finish order in the log (PHASE3 3by)."""
        result = subprocess.run(
            [sys.executable, '-B', '-I', str(Path(__file__).with_name('run_tests.py')),
             '--workers', '1', '--durations', '5', 'test_runners.TimedExample'],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r'test_runners\.TimedExample\.test_sleep: PASS \(\d+\.\d s\)')
        if sys.version_info >= (3, 12):   # unittest's durations arrived in 3.12
            self.assertRegex(result.stdout, r'\n  \d+\.\d{3}s  test_sleep\n')

    def test_explicit_test_ids_keep_one_process_per_case(self):
        result = subprocess.run(
            [sys.executable, '-B', '-I', str(Path(__file__).with_name('run_tests.py')),
             '--workers', '1', 'test_runners.WorkerExample'],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('1 processes', result.stdout)

    def test_a_hanging_case_fails_at_the_timeout_instead_of_stalling_the_run(self):
        """A hung child used to stall the run until CI cancelled the job, with no output (PHASE3 3bp)."""
        from run_tests import DEFAULT_TIMEOUT

        started = time.monotonic()
        result = subprocess.run(
            [sys.executable, '-B', '-I', str(Path(__file__).with_name('run_tests.py')),
             '--workers', '1', '--timeout', '1', 'test_runners.HangingExample'],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('timed out after 1 s', result.stdout)
        self.assertLess(time.monotonic() - started, 30)
        # Far above the slowest suite (about 30 s locally), far below the 10-minute job limit.
        self.assertTrue(120 <= DEFAULT_TIMEOUT <= 300, DEFAULT_TIMEOUT)

    def test_runs_test_cases_in_parallel_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, '-B', '-I', str(Path(__file__).with_name('run_tests.py')),
                 '--workers', '2', 'test_runners.ParallelExample'],
                env={**os.environ, 'RUNNER_RENDEZVOUS': directory},
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('2 workers', result.stdout)


class TimedExample(unittest.TestCase):
    """Explicitly selected child case with a measurable duration; excluded from the default runner suite."""

    def test_sleep(self):
        time.sleep(0.05)


class ParallelExample(unittest.TestCase):
    """Explicitly selected child cases; excluded from the default runner suite."""

    def rendezvous(self, name, peer):
        directory = Path(os.environ['RUNNER_RENDEZVOUS'])
        (directory / name).write_text(str(os.getpid()))
        deadline = time.monotonic() + 5
        while not (directory / peer).exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue((directory / peer).exists(), 'peer case did not run concurrently')
        self.assertNotEqual((directory / peer).read_text(), str(os.getpid()))

    def test_first(self):
        self.rendezvous('first', 'second')

    def test_second(self):
        self.rendezvous('second', 'first')


class FailingExample(unittest.TestCase):
    def test_failure(self):
        self.fail('intentional child failure')


class HangingExample(unittest.TestCase):
    def test_hang(self):
        while True:
            time.sleep(0.1)


def worker_directory():
    return str(Path.cwd())


class WorkerExample(unittest.TestCase):
    def test_cleanup(self):
        from run_mutations import prepare_worker

        root = str(Path(__file__).resolve().parent.parent)
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=1, initializer=prepare_worker, initargs=(root,),
        ) as pool:
            directory = pool.submit(worker_directory).result()
            self.assertTrue((Path(directory) / 'tools/test_ci.py').is_file())
        self.assertFalse(Path(directory).exists())


def load_tests(loader, tests, pattern):
    # Helper cases only run when explicitly selected by the regression tests.
    return loader.loadTestsFromTestCase(RunnerChecks)


if __name__ == '__main__':
    unittest.main(defaultTest='RunnerChecks')
