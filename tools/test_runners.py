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
