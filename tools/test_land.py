"""Checks for land_branch.py against throwaway Git repositories (needs git on PATH)."""
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

IDENTITY = {'GIT_AUTHOR_NAME': 'Test', 'GIT_AUTHOR_EMAIL': 'test@example.invalid',
            'GIT_COMMITTER_NAME': 'Test', 'GIT_COMMITTER_EMAIL': 'test@example.invalid'}


def git(cwd, *args):
    result = subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True,
                            env={**os.environ, **IDENTITY})
    if result.returncode:
        raise AssertionError(f'git {" ".join(args)} failed: {result.stderr}')
    return result.stdout.strip()


def commit(cwd, name, text='x'):
    (Path(cwd) / name).write_text(text, encoding='utf-8')
    git(cwd, 'add', name)
    git(cwd, 'commit', '-q', '-m', f'add {name}')
    return git(cwd, 'rev-parse', 'HEAD')


class LandChecks(unittest.TestCase):
    def setUp(self):
        os.environ.update(IDENTITY)
        self.tmp = Path(tempfile.mkdtemp())
        self.main = self.tmp / 'main'
        self.main.mkdir()
        git(self.main, 'init', '-q')
        git(self.main, 'symbolic-ref', 'HEAD', 'refs/heads/main')
        commit(self.main, 'base.txt')
        self.remote = self.tmp / 'remote.git'
        git(self.tmp, 'clone', '-q', '--bare', str(self.main), str(self.remote))
        git(self.main, 'remote', 'add', 'origin', str(self.remote))
        git(self.main, 'fetch', '-q', 'origin')
        self.feat = self.tmp / 'feat'
        git(self.main, 'worktree', 'add', '-q', '-b', 'feat', str(self.feat), 'main')

    def tearDown(self):
        for key in IDENTITY:
            os.environ.pop(key, None)
        # Worktree files can stay read-only on Windows; ignore cleanup failures.
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def land(self, *args):
        from land_branch import main
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = main(['--repo', str(self.feat), *args])
        return code, out.getvalue()

    def sha(self, ref):
        return git(self.main, 'rev-parse', ref)

    def test_fast_forwards_main_checked_out_in_another_worktree(self):
        tip = commit(self.feat, 'a.txt')
        code, out = self.land()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.sha('main'), tip)
        self.assertEqual((self.main / 'a.txt').read_text(encoding='utf-8'), 'x')  # its checkout moved too
        self.assertEqual(git(self.main, 'rev-list', '--merges', '--count', 'main'), '0')
        self.assertIn('fast-forwarded main', out)

    def test_moves_main_ref_when_no_worktree_has_it(self):
        git(self.main, 'checkout', '-q', '--detach')
        tip = commit(self.feat, 'a.txt')
        code, out = self.land()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.sha('main'), tip)

    def test_names_the_branch_explicitly(self):
        tip = commit(self.feat, 'a.txt')
        from land_branch import main
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--repo', str(self.main), 'feat']), 0)
        self.assertEqual(self.sha('main'), tip)

    def test_refuses_when_main_has_commits_the_branch_lacks(self):
        before = commit(self.main, 'm.txt')
        commit(self.feat, 'a.txt')
        code, out = self.land()
        self.assertEqual(code, 1)
        self.assertEqual(self.sha('main'), before)
        self.assertIn('git rebase main', out)

    def test_rebase_option_replays_the_branch_then_fast_forwards(self):
        commit(self.main, 'm.txt')
        commit(self.feat, 'a.txt')
        code, out = self.land('--rebase')
        self.assertEqual(code, 0, out)
        self.assertEqual(self.sha('main'), self.sha('feat'))
        self.assertEqual(git(self.main, 'rev-list', '--merges', '--count', 'main'), '0')
        self.assertEqual(git(self.main, 'rev-list', '--count', 'main'), '3')

    def test_rebase_conflict_is_aborted_and_nothing_moves(self):
        main_before = commit(self.main, 'same.txt', 'main')
        feat_before = commit(self.feat, 'same.txt', 'feat')
        code, out = self.land('--rebase')
        self.assertEqual(code, 1)
        self.assertEqual(self.sha('main'), main_before)
        self.assertEqual(self.sha('feat'), feat_before)
        self.assertEqual(git(self.feat, 'status', '--porcelain'), '')
        self.assertIn('rebase stopped', out)

    def test_refuses_a_dirty_main_checkout(self):
        before = self.sha('main')
        commit(self.feat, 'a.txt')
        (self.main / 'base.txt').write_text('edited', encoding='utf-8')
        code, out = self.land()
        self.assertEqual(code, 1)
        self.assertEqual(self.sha('main'), before)
        self.assertIn('uncommitted changes', out)

    def test_refuses_a_dirty_branch_checkout_when_rebasing(self):
        commit(self.main, 'm.txt')
        commit(self.feat, 'a.txt')
        (self.feat / 'a.txt').write_text('edited', encoding='utf-8')
        code, out = self.land('--rebase')
        self.assertEqual(code, 1)
        self.assertIn('uncommitted changes', out)

    def push_elsewhere(self):
        other = self.tmp / 'other'
        git(self.tmp, 'clone', '-q', str(self.remote), str(other))
        commit(other, 'o.txt')
        git(other, 'push', '-q', 'origin', 'HEAD:main')

    def test_fetches_and_refuses_when_origin_main_moved_on(self):
        self.push_elsewhere()
        before = self.sha('main')
        commit(self.feat, 'a.txt')
        code, out = self.land()
        self.assertEqual(code, 1)
        self.assertEqual(self.sha('main'), before)
        self.assertIn('git rebase origin/main', out)

    def test_no_fetch_uses_the_last_fetched_copy(self):
        self.push_elsewhere()
        tip = commit(self.feat, 'a.txt')
        code, out = self.land('--no-fetch')
        self.assertEqual(code, 0, out)
        self.assertEqual(self.sha('main'), tip)

    def test_refuses_when_main_and_origin_main_diverged(self):
        self.push_elsewhere()
        before = commit(self.main, 'm.txt')
        code, out = self.land('--rebase')
        self.assertEqual(code, 1)
        self.assertEqual(self.sha('main'), before)
        self.assertIn('have diverged', out)

    def test_dry_run_reports_without_moving(self):
        before = self.sha('main')
        commit(self.feat, 'a.txt')
        code, out = self.land('--dry-run')
        self.assertEqual(code, 0, out)
        self.assertEqual(self.sha('main'), before)
        self.assertIn('would fast-forward main', out)

    def test_refuses_landing_main_onto_itself_and_nothing_to_land(self):
        from land_branch import main
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['--repo', str(self.main), '--no-fetch']), 1)
        self.assertIn('is the target', out.getvalue())
        code, out = self.land('--no-fetch')
        self.assertEqual(code, 0, out)
        self.assertIn('already contains', out)

    def test_never_pushes(self):
        before = git(self.remote, 'rev-parse', 'main')
        commit(self.feat, 'a.txt')
        self.assertEqual(self.land()[0], 0)
        self.assertEqual(git(self.remote, 'rev-parse', 'main'), before)


if __name__ == '__main__':
    unittest.main()
