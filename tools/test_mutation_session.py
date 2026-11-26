"""Mutation runner CLI checks using a tiny independent project and real Cosmic Ray databases."""
import json
from contextlib import closing
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class SessionChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'sdk_mods').mkdir()
        (self.root / 'tools').mkdir()
        (self.root / 'sdk_mods/subject.py').write_text('value = 1\n', encoding='utf-8')
        (self.root / 'tools/check.py').write_text(
            "import runpy\nassert runpy.run_path('sdk_mods/subject.py').get('value') == 1\n", encoding='utf-8')
        (self.root / 'cosmic-ray.toml').write_text(
            '[cosmic-ray]\nmodule-path = ["sdk_mods/subject.py"]\ntimeout = 60.0\n'
            'excluded-modules = []\ntest-command = "python -B -I tools/check.py"\n'
            '[cosmic-ray.distributor]\nname = "local"\n', encoding='utf-8')
        self.output = self.root / 'dist/ci'

    def cli(self, *args):
        return subprocess.run([sys.executable, '-B', '-I', str(HERE / 'run_mutations.py'),
                               '--project', str(self.root), '--workers', '1', *args],
                              capture_output=True, text=True, timeout=45)

    def test_resume_keeps_results_and_denominator_and_runs_only_pending_items(self):
        first = self.cli('--max-results', '1')
        self.assertEqual(first.returncode, 2, first.stdout + first.stderr)
        counts = json.loads((self.output / 'mutations.json').read_bytes())['sdk_mods/subject.py']
        self.assertGreater(counts['total'], 1)
        self.assertEqual(counts['pending'], counts['total'] - 1)
        with closing(sqlite3.connect(self.output / 'mutations.sqlite')) as db:
            prior = db.execute('select job_id, output from work_results').fetchall()
        resumed = self.cli('--resume')
        self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
        after = json.loads((self.output / 'mutations.json').read_bytes())['sdk_mods/subject.py']
        self.assertEqual(after['total'], counts['total'])
        self.assertEqual(after['pending'], 0)
        self.assertEqual(after['killed'] + after['survived'] + after['timeout'] + after['error'], after['total'])
        with closing(sqlite3.connect(self.output / 'mutations.sqlite')) as db:
            self.assertEqual(db.execute('select job_id, output from work_results where job_id = ?', (prior[0][0],)).fetchall(), prior)

    def test_changed_source_cannot_resume_or_destroy_previous_results(self):
        first = self.cli('--max-results', '1')
        self.assertEqual(first.returncode, 2, first.stdout + first.stderr)
        before = (self.output / 'mutations.json').read_bytes()
        (self.root / 'sdk_mods/subject.py').write_text('value = 2\n', encoding='utf-8')
        resumed = self.cli('--resume')
        self.assertNotEqual(resumed.returncode, 0)
        self.assertIn('cannot resume', resumed.stdout + resumed.stderr)
        self.assertEqual((self.output / 'mutations.json').read_bytes(), before)

    def test_timeout_remains_undetected_and_survivors_are_preserved_on_resume(self):
        # Every mutation still runs the same sleeping command: baseline completes, mutants time out.
        (self.root / 'tools/check.py').write_text('import time\ntime.sleep(0.2)\n', encoding='utf-8')
        config = self.root / 'cosmic-ray.toml'
        config.write_text(config.read_text(encoding='utf-8').replace('timeout = 60.0', 'timeout = 0.05'), encoding='utf-8')
        result = self.cli('--max-results', '1')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        count = json.loads((self.output / 'mutations.json').read_bytes())['sdk_mods/subject.py']
        self.assertEqual((count['killed'], count['timeout']), (0, 1))
        survivors = json.loads((self.output / 'mutation-survivors.json').read_bytes())
        self.assertEqual(survivors[0]['outcome'], 'timeout')
        result = self.cli('--resume')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        count = json.loads((self.output / 'mutations.json').read_bytes())['sdk_mods/subject.py']
        self.assertEqual(count['timeout'], count['total'])
        self.assertEqual(count['killed'], 0)
        self.assertIn(survivors[0], json.loads((self.output / 'mutation-survivors.json').read_bytes()))

    def test_progress_checkpoint_is_readable_while_next_mutant_is_stuck(self):
        marker = self.root / 'first-result'
        (self.root / 'tools/check.py').write_text(
            "import runpy, time\n"
            "if runpy.run_path('sdk_mods/subject.py').get('value') != 1:\n"
            "    try:\n"
            f"        open({str(marker)!r}, 'x').close()\n"
            "    except FileExistsError:\n"
            "        time.sleep(120)\n"
            "    raise SystemExit(1)\n", encoding='utf-8')
        # Redirect output to a file so the parent can observe a flushed progress line without blocking.
        import time
        log = self.root / 'runner.log'
        with log.open('w', encoding='utf-8') as stream:
            process = subprocess.Popen([sys.executable, '-B', '-I', str(HERE / 'run_mutations.py'),
                                        '--project', str(self.root), '--workers', '1', '--progress-every', '1',
                                        '--stall-timeout', '5'], stdout=stream, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline and process.poll() is None:
                    if '1/' in log.read_text(encoding='utf-8'):
                        break
                    time.sleep(0.05)
                self.assertIsNone(process.poll(), log.read_text(encoding='utf-8'))
                count = json.loads((self.output / 'mutations.json').read_bytes())['sdk_mods/subject.py']
                self.assertEqual(count['killed'], 1)
                self.assertEqual(count['pending'], count['total'] - 1)
                self.assertEqual(process.wait(timeout=20), 2)
            finally:
                if process.poll() is None:
                    subprocess.run(['taskkill', '/F', '/T', '/PID', str(process.pid)] if sys.platform == 'win32'
                                   else ['kill', '-9', str(process.pid)], capture_output=True)
                    process.wait(timeout=10)

    def test_no_progress_alarm_exits_keeps_pending_and_kills_stuck_process_tree(self):
        pid_file = self.root / 'child.pid'
        (self.root / 'tools/check.py').write_text(
            "import runpy, subprocess, sys\n"
            "if runpy.run_path('sdk_mods/subject.py').get('value') != 1:\n"
            "    subprocess.run([sys.executable, '-I', 'tools/hang.py'])\n", encoding='utf-8')
        (self.root / 'tools/hang.py').write_text(
            f"import os, time\nopen({str(pid_file)!r}, 'w').write(str(os.getpid()))\ntime.sleep(120)\n", encoding='utf-8')
        result = self.cli('--max-results', '1', '--stall-timeout', '3')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('no progress', result.stdout.lower() + result.stderr.lower())
        self.assertIn('worker PID', result.stdout)
        counts = json.loads((self.output / 'mutations.json').read_bytes())['sdk_mods/subject.py']
        self.assertEqual(counts['pending'], counts['total'])
        self.assertEqual(counts['killed'], 0)
        self.assertTrue(pid_file.exists(), result.stdout + result.stderr)
        sys.path.insert(0, str(HERE))
        from test_runners import process_alive
        self.assertFalse(process_alive(int(pid_file.read_text())), 'stuck grandchild survived alarm')


if __name__ == '__main__':
    unittest.main()
