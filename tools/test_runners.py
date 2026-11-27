"""Regression checks for automatic test worker selection and runner exit status."""
import os
import concurrent.futures
import io
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
        test_swfmerge, so those must be in the command too (PHASE3 §3cf)."""
        import test_mutants

        cases = test_mutants.case_suites()
        self.assertIn('test_ci.py::SourceChecks.test_mod_without_game_assets', cases)
        self.assertIn('test_ci.py::SourceChecks.test_original_art_movie_passes_both_suites', cases)
        self.assertTrue(all(case.startswith('test_ci.py::') for case in cases))
        # the three builder suites import no SDK stubs, so they share one process (a process costs about 0.7 s)
        self.assertEqual(set(test_mutants.OTHER_SUITES), {'test_builder_suites.py', 'test_profiler.py'})

    def test_probe_mode_ignores_the_per_file_lists_and_a_normal_run_follows_them(self):
        import test_mutants

        everything = test_mutants.OTHER_SUITES + test_mutants.case_suites()
        listed = 'sdk_mods/classic_minimap/hudmovie.py'
        self.assertEqual(test_mutants.run_suites({}), everything)
        self.assertEqual(test_mutants.run_suites({'MINIMAP_MUTATED_FILE': listed}), test_mutants.suites_for(listed))
        self.assertNotEqual(test_mutants.suites_for(listed), everything)
        self.assertEqual(test_mutants.run_suites({'MINIMAP_MUTATED_FILE': listed, 'MINIMAP_SUITE_PROBE': 'x.jsonl'}),
                         everything, 'a probe measures every suite, whatever the file lists')

    def test_builder_suites_run_together_in_one_process_and_stop_at_the_first_failure(self):
        import tempfile
        import test_builder_suites

        self.assertEqual(test_builder_suites.NAMES, ('test_builder_formats', 'test_swfmerge', 'test_hudmovie'))
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'fake_ok.py').write_text('import unittest\nclass A(unittest.TestCase):\n'
                                               '    def test_a(self):\n        pass\n')
            Path(tmp, 'fake_bad.py').write_text('import unittest\nclass B(unittest.TestCase):\n'
                                                '    def test_b(self):\n        self.fail("boom")\n'
                                                '    def test_c(self):\n        raise SystemExit("not reached")\n')
            sys.path.insert(0, tmp)
            try:
                stream = io.StringIO()
                self.assertEqual(test_builder_suites.main(('fake_ok',), stream), 0)
                self.assertEqual(test_builder_suites.main(('fake_ok', 'fake_bad'), stream), 1)
                self.assertIn('boom', stream.getvalue())
            finally:
                sys.path.remove(tmp)
                for name in ('fake_ok', 'fake_bad'):
                    sys.modules.pop(name, None)
        # the real three, together
        self.assertEqual(test_builder_suites.main(stream=io.StringIO()), 0)

    @unittest.skipIf(sys.platform == 'win32', 'RLIMIT_AS exists on POSIX only')
    def test_a_suite_cannot_allocate_past_the_memory_cap(self):
        """A mutant that grows memory without bound must fail its own suite, not take the CI runner down (the
        runner was shut down twice mid-run, exit 143)."""
        import test_mutants

        code = 'import sys\ntry:\n    bytearray(sys.argv[1])\nexcept MemoryError:\n    sys.exit(7)\n'
        cap = test_mutants.MEMORY_CAP
        for size, expected in ((cap // 8, 0), (cap * 2, 7)):
            proc = subprocess.run([sys.executable, '-c', code, str(size)], preexec_fn=test_mutants.limit_memory)
            self.assertEqual(proc.returncode, expected, size)

    def test_every_mutated_file_has_a_suite_list_and_unknown_files_run_everything(self):
        """A file's list names real suites, the whole of test_ci only as 'test_ci.py', and a file with no list (or
        no file at all) gets every suite, so only a measured entry can skip one."""
        import tomllib
        import test_mutants

        tools = Path(__file__).resolve().parent
        config = tomllib.loads((tools.parent / 'cosmic-ray.toml').read_text())
        everything = test_mutants.OTHER_SUITES + test_mutants.case_suites()
        for module in config['cosmic-ray']['module-path']:
            listed = test_mutants.SUITES_BY_FILE.get(module)
            self.assertTrue(listed, f'{module} has no suite list')
            self.assertEqual(len(set(listed)), len(listed))
            for suite in listed:
                script, _, case = suite.partition('::')
                self.assertTrue((tools / script).exists(), f'{module}: {suite} is not a suite')
                self.assertTrue(not case or suite in test_mutants.case_suites(), f'{module}: {suite} is not a case')
            self.assertLessEqual(set(test_mutants.suites_for(module)), set(everything))
        self.assertEqual(test_mutants.suites_for(None), everything)
        self.assertEqual(test_mutants.suites_for('tools/never_listed.py'), everything)
        table = {'a/x.py': ('test_swfmerge.py', 'test_ci.py')}
        self.assertEqual(test_mutants.suites_for('a\\x.py', table),
                         ('test_swfmerge.py',) + test_mutants.case_suites())

    def test_mutation_worker_tells_the_command_which_file_it_mutates(self):
        import os
        import run_mutations
        from pathlib import PurePosixPath
        from types import SimpleNamespace

        seen = {}

        def fake(mutations, command, timeout):
            seen['file'] = os.environ.get('MINIMAP_MUTATED_FILE')
            return 'result'

        item = SimpleNamespace(mutations=[SimpleNamespace(module_path=PurePosixPath('sdk_mods/m/x.py'))])
        original = run_mutations.mutate_and_test
        run_mutations.mutate_and_test = fake
        try:
            returned, result, seconds = run_mutations.run_item(item, 'cmd', 1)
        finally:
            run_mutations.mutate_and_test = original
            os.environ.pop('MINIMAP_MUTATED_FILE', None)
        self.assertEqual((returned, result), (item, 'result'))
        self.assertGreaterEqual(seconds, 0.0, 'the worker also reports how long the mutant took')
        self.assertEqual(seen['file'], 'sdk_mods/m/x.py')

    def test_mutation_progress_line_shows_the_recent_rate_beside_the_average(self):
        from run_mutations import progress_suffix

        # 600 in 6 minutes overall, but the last 200 took 40 s: 300 a minute now
        self.assertEqual(progress_suffix(600, 1200, 360, recent=(200, 40)),
                         ' | 100.0/min (last 200: 300.0/min), ETA 12m 00s')
        self.assertEqual(progress_suffix(600, 0, 360, recent=(200, 40)), ' | 100.0/min (last 200: 300.0/min), done')
        self.assertEqual(progress_suffix(600, 1200, 360, recent=(200, 0)), ' | 100.0/min, ETA 12m 00s',
                         'no recent rate from a zero interval')

    def test_mutation_time_log_and_report_point_at_slow_spots(self):
        import json
        import tempfile
        from pathlib import PurePosixPath
        from types import SimpleNamespace

        import mutation_times
        from run_mutations import time_record

        item = SimpleNamespace(job_id='j1', mutations=[SimpleNamespace(
            module_path=PurePosixPath('sdk_mods/m/x.py'), operator_name='core/NumberReplacer', occurrence=7)])
        result = SimpleNamespace(worker_outcome=SimpleNamespace(value='normal'),
                                 test_outcome=SimpleNamespace(value='survived'))
        self.assertEqual(time_record(item, result, 4.25),
                         {'job': 'j1', 'file': 'sdk_mods/m/x.py', 'operator': 'core/NumberReplacer',
                          'occurrence': 7, 'seconds': 4.25, 'outcome': 'survived'})
        # Cosmic Ray records a timeout as a kill with output 'timeout'; the gate counts it undetected, so must the log
        hung = SimpleNamespace(test_outcome=SimpleNamespace(value='killed'), output='timeout')
        self.assertEqual(time_record(item, hung, 20.1)['outcome'], 'timeout')

        rows = [dict(job='a', file='x.py', operator='op1', occurrence=1, seconds=1.0, outcome='killed'),
                dict(job='b', file='x.py', operator='op2', occurrence=2, seconds=9.0, outcome='survived'),
                dict(job='c', file='y.py', operator='op1', occurrence=3, seconds=2.0, outcome='killed')]
        summary = mutation_times.summarize(rows, slowest=2)
        self.assertEqual(summary['files'], [
            {'name': 'x.py', 'count': 2, 'seconds': 10.0, 'mean': 5.0, 'max': 9.0, 'survived': 1},
            {'name': 'y.py', 'count': 1, 'seconds': 2.0, 'mean': 2.0, 'max': 2.0, 'survived': 0}])
        self.assertEqual([r['job'] for r in summary['slowest']], ['b', 'c'])
        self.assertEqual(summary['operators'][0], {'name': 'op2', 'count': 1, 'seconds': 9.0, 'mean': 9.0})
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp, 'times.jsonl')
            log.write_text('\n'.join(json.dumps(r) for r in rows) + '\n\n')
            self.assertEqual(mutation_times.load(log), rows)
            self.assertIn('x.py', mutation_times.render(summary))

    def test_probe_mode_runs_every_suite_and_logs_the_failing_ones(self):
        import json
        import os
        import tempfile
        import test_mutants

        with tempfile.TemporaryDirectory() as tmp:
            good, bad, log = Path(tmp, 'good.py'), Path(tmp, 'bad.py'), Path(tmp, 'probe.jsonl')
            good.write_text('')
            bad.write_text('raise SystemExit(5)\n')
            os.environ.update({'MINIMAP_SUITE_PROBE': str(log), 'MINIMAP_MUTATED_FILE': 'a/x.py'})
            try:
                self.assertEqual(test_mutants.main(suites=[str(bad), str(good), str(bad)], budget=20), 1)
            finally:
                del os.environ['MINIMAP_SUITE_PROBE'], os.environ['MINIMAP_MUTATED_FILE']
            self.assertEqual(json.loads(log.read_text()), {'file': 'a/x.py', 'failed': [str(bad), str(bad)]})

    def test_mutation_progress_line_shows_throughput_and_eta(self):
        from run_mutations import progress_suffix

        # 600 results in 6 minutes is 100 a minute; 1,200 left take 12 minutes
        self.assertEqual(progress_suffix(600, 1200, 360), ' | 100.0/min, ETA 12m 00s')
        self.assertEqual(progress_suffix(50, 6000, 60), ' | 50.0/min, ETA 2h 00m')
        self.assertEqual(progress_suffix(90, 10, 60), ' | 90.0/min, ETA 0m 07s')
        self.assertEqual(progress_suffix(600, 0, 360), ' | 100.0/min, done')
        self.assertEqual(progress_suffix(0, 100, 30), '', 'no rate before the first result')
        self.assertEqual(progress_suffix(5, 100, 0), '', 'no rate without elapsed time')

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
