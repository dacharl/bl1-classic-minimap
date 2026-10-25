"""Land a task branch on main by fast-forward only, keeping history linear (AGENTS.md "Commits").

    python -I tools/land_branch.py [branch] [--onto main] [--rebase] [--no-fetch] [--dry-run]

The branch defaults to the one checked out in --repo (default: the current directory). The tool
fetches origin's copy of the target, refuses if the target and origin's copy have diverged, and needs
the branch to contain the newer of the two; --rebase replays the branch onto it first (aborting on a
conflict). It then moves the target: `merge --ff-only` in the worktree that has it checked out (which
must be clean), or a guarded ref update when none does. It never creates merge commits and never pushes.
"""
import argparse
import subprocess
import sys


class Refused(Exception):
    pass


def git(repo, *args, check=True):
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True)
    if check and result.returncode:
        raise Refused(f'git {" ".join(args)} failed: {result.stderr.strip()}')
    return result


def out(repo, *args):
    return git(repo, *args).stdout.strip()


def exists(repo, ref):
    return git(repo, 'rev-parse', '--verify', '-q', ref + '^{commit}', check=False).returncode == 0


def contains(repo, ancestor, descendant):
    return git(repo, 'merge-base', '--is-ancestor', ancestor, descendant, check=False).returncode == 0


def worktree_of(repo, branch):
    """Path of the worktree with `branch` checked out, or None."""
    path = None
    for line in out(repo, 'worktree', 'list', '--porcelain').splitlines():
        if line.startswith('worktree '):
            path = line[len('worktree '):]
        elif line == f'branch refs/heads/{branch}':
            return path
    return None


def require_clean(path, what):
    if out(path, 'status', '--porcelain', '--untracked-files=no'):
        raise Refused(f'{what} at {path} has uncommitted changes; commit or set them aside first')


def newest_base(repo, target, remote, fetch):
    """The newer of `target` and `remote/target`; refuses when they have diverged."""
    upstream = f'{remote}/{target}'
    if fetch:
        git(repo, 'fetch', '-q', remote, f'+refs/heads/{target}:refs/remotes/{upstream}')
    if not exists(repo, upstream) or contains(repo, upstream, target):
        return target
    if contains(repo, target, upstream):
        return upstream
    raise Refused(f'{target} and {upstream} have diverged; reconcile {target} before landing')


def land(repo, branch, target, remote, rebase, fetch, dry_run):
    if branch == target:
        raise Refused(f'{branch} is the target; name the task branch to land')
    for ref in (branch, target):
        if not exists(repo, ref):
            raise Refused(f'no branch named {ref}')
    base = newest_base(repo, target, remote, fetch)
    if not contains(repo, base, branch):
        if not rebase:
            raise Refused(f'{branch} lacks commits on {base}; run `git rebase {base}` in its worktree '
                          'or pass --rebase')
        where = worktree_of(repo, branch)
        if where is None:
            raise Refused(f'check {branch} out in a worktree so it can be rebased')
        require_clean(where, branch)
        if dry_run:
            print(f'would rebase {branch} onto {base}')
        elif git(where, 'rebase', '-q', base, check=False).returncode:
            git(where, 'rebase', '--abort', check=False)
            raise Refused(f'rebase stopped on a conflict and was aborted; rebase {branch} onto {base} by hand')
        else:
            print(f'rebased {branch} onto {base}')
    tip, old = out(repo, 'rev-parse', branch), out(repo, 'rev-parse', target)
    if tip == old:
        print(f'{target} already contains {branch}')
        return
    count = out(repo, 'rev-list', '--count', f'{target}..{branch}')
    if dry_run:
        print(f'would fast-forward {target} by {count} commit(s) to {tip[:7]}')
        return
    where = worktree_of(repo, target)
    if where is None:
        git(repo, 'update-ref', '-m', f'land_branch: fast-forward to {branch}', f'refs/heads/{target}', tip, old)
    else:
        require_clean(where, target)
        git(where, 'merge', '-q', '--ff-only', branch)
    print(f'fast-forwarded {target} by {count} commit(s) to {tip[:7]} ({branch}); nothing pushed')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('branch', nargs='?', help='branch to land (default: the one checked out in --repo)')
    parser.add_argument('--onto', default='main', help='target branch (default: main)')
    parser.add_argument('--remote', default='origin', help="remote whose copy of the target to respect")
    parser.add_argument('--repo', default='.', help='any worktree of the repository (default: .)')
    parser.add_argument('--rebase', action='store_true', help='rebase the branch onto the target first if needed')
    parser.add_argument('--no-fetch', dest='fetch', action='store_false', help="don't fetch the remote first")
    parser.add_argument('--dry-run', action='store_true', help='report what would happen; change nothing')
    args = parser.parse_args(argv)
    try:
        branch = args.branch or out(args.repo, 'rev-parse', '--abbrev-ref', 'HEAD')
        land(args.repo, branch, args.onto, args.remote, args.rebase, args.fetch, args.dry_run)
    except Refused as refusal:
        print(f'refused: {refusal}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
