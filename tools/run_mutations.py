"""Run every Cosmic Ray mutant in isolated source copies, with no game assets.

Usage: python -I tools/run_mutations.py [--workers auto|N] [--resume] [--stall-timeout 600]
All outcomes, including timeouts and tool failures, remain in the denominator.
Use --max-results N for a bounded incomplete run; compatible --resume retains all prior results.
"""
import argparse
import concurrent.futures
import hashlib
import importlib.metadata
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from collections import Counter
from pathlib import Path
from multiprocessing.util import Finalize

from cosmic_ray.commands.init import init
from cosmic_ray.config import load_config
from cosmic_ray.mutating import mutate_and_test
from cosmic_ray.work_db import WorkDB, use_db

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
from parallel_workers import worker_count  # noqa: E402

WORKSPACE = None


def cleanup_worker(root):
    # Windows cannot remove a directory while it is the process's working directory.
    os.chdir(root)
    if WORKSPACE is not None:
        target = Path(WORKSPACE).resolve()
        if target.parent != Path(tempfile.gettempdir()).resolve() or not target.name.startswith('minimap-mutations-'):
            raise ValueError(f'Unexpected worker directory: {target}')
        shutil.rmtree(target)


def prepare_worker(root, registry=None):
    global WORKSPACE
    # One finalizer owns cleanup. TemporaryDirectory's weakref finalizer can run
    # before multiprocessing finalizers on Python 3.13, while cwd is still here.
    WORKSPACE = tempfile.mkdtemp(prefix='minimap-mutations-')
    if registry is not None:
        (Path(registry) / f'{os.getpid()}.json').write_text(json.dumps({'workspace': WORKSPACE}), encoding='utf-8')
    Finalize(None, cleanup_worker, args=(root,), exitpriority=10)
    target = Path(WORKSPACE)
    for folder in ('tools', 'sdk_mods'):
        shutil.copytree(Path(root) / folder, target / folder,
                        ignore=shutil.ignore_patterns('__pycache__', 'pk', '*.pyc', '*.pyo'))
    os.chdir(target)


def run_item(item, command, timeout):
    # test_mutants.py picks its suites from this; each worker process handles one mutant at a time.
    os.environ['MINIMAP_MUTATED_FILE'] = item.mutations[0].module_path.as_posix()
    began = time.monotonic()
    result = mutate_and_test(item.mutations, command, timeout)
    return item, result, time.monotonic() - began


def time_record(item, result, seconds):
    """One line of dist/ci/mutation-times.jsonl: which mutant, how long it took, how it ended."""
    mutation = item.mutations[0]
    return dict(job=item.job_id, file=mutation.module_path.as_posix(), operator=mutation.operator_name,
                occurrence=mutation.occurrence, seconds=round(seconds, 3),
                outcome=getattr(getattr(result, 'test_outcome', None), 'value', None))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=worker_count, default='auto',
                        help='auto (available CPUs) or a positive integer')
    parser.add_argument('--modules', nargs='+', default=[],
                        help='run only these configured module paths (local measurement; CI runs all)')
    parser.add_argument('--project', type=Path, default=ROOT, help='source project (default: this checkout)')
    parser.add_argument('--resume', action='store_true', help='continue the existing compatible database')
    parser.add_argument('--max-results', type=int, help='stop after N new results, leaving the rest pending')
    parser.add_argument('--stall-timeout', type=float, default=600.0, help='seconds without a completed result (default 600)')
    parser.add_argument('--progress-every', type=int, default=50, help='checkpoint/print every N results (default 50)')
    args = parser.parse_args(argv)
    if args.max_results is not None and args.max_results < 1:
        parser.error('--max-results must be positive')
    import math
    if not math.isfinite(args.stall_timeout) or args.stall_timeout <= 0 or args.progress_every < 1:
        parser.error('--stall-timeout and --progress-every must be positive and finite')
    if sys.platform == 'win32' and args.workers > 61:
        args.workers = 61  # ProcessPoolExecutor's Windows handle limit.
    return args


def selected_modules(configured, wanted):
    """The configured module paths, optionally narrowed to `wanted` (configured order kept)."""
    unknown = set(wanted) - set(configured)
    if unknown:
        raise SystemExit(f'Not in cosmic-ray.toml module-path: {", ".join(sorted(unknown))}')
    return [path for path in configured if not wanted or path in wanted]


def fingerprint(root, paths):
    """Resume only with the same source, tests, fixtures, configuration and interpreter/dependencies."""
    files = {root / 'cosmic-ray.toml', root / 'pyproject.toml', *[root / p for p in paths]}
    for folder in ('tools', 'sdk_mods'):
        files.update(p for p in (root / folder).rglob('*') if p.is_file()
                     and not {'__pycache__', 'pk'} & set(p.parts) and p.suffix in ('.py', '.json', '.toml'))
    hashes = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(files) if p.exists()}
    dependencies = sorted((d.metadata['Name'], d.version) for d in importlib.metadata.distributions())
    return dict(files=hashes, modules=[p.as_posix() for p in paths], python=sys.version,
                executable=sys.executable, dependencies=dependencies)


@contextmanager
def session_lock(output):
    """OS locks release even on a crash; a retained lock file never needs stale-lock deletion."""
    with (output / '.mutation.lock').open('a+b') as lock:
        lock.seek(0, 2)
        if lock.tell() == 0:
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        try:
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise SystemExit('mutation session is already in use') from error
        try:
            yield
        finally:
            lock.seek(0)
            if sys.platform == 'win32':
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def write_json(path, data):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def report(db, paths, output):
    counts = {p.as_posix(): Counter(total=0, killed=0, survived=0, timeout=0, error=0, pending=0) for p in paths}
    survivors = []
    results = dict(db.results)
    for item in db.work_items:
        name = item.mutations[0].module_path.as_posix()
        tally = counts[name]
        tally['total'] += 1
        result = results.get(item.job_id)
        if result is None:
            outcome = 'pending'
        elif result.worker_outcome != 'normal' or result.test_outcome not in {'killed', 'survived'}:
            outcome = 'error'
        elif result.output == 'timeout':
            outcome = 'timeout'
        else:
            outcome = result.test_outcome.value
        tally[outcome] += 1
        if result is not None and outcome != 'killed':
            survivors.append(dict(job_id=item.job_id, module=name, outcome=outcome,
                                  diff=result.diff, output=result.output))
    write_json(output / 'mutations.json', counts)
    write_json(output / 'mutation-survivors.json', survivors)
    return counts


def progress_suffix(completed, remaining, elapsed, recent=None):
    """' | 100.0/min, ETA 12m 00s' from the results finished this session, the ones still to run and the seconds
    since it started; '' until there is a rate. The ETA is the remaining count at the average rate so far.
    `recent` is (results, seconds) since the last checkpoint: its rate is shown beside the average, so a slow
    stretch is visible as it happens."""
    if completed <= 0 or elapsed <= 0:
        return ''
    per_minute = completed * 60 / elapsed
    now = ''
    if recent and recent[1] > 0:
        now = f' (last {recent[0]}: {recent[0] * 60 / recent[1]:.1f}/min)'
    if remaining <= 0:
        return f' | {per_minute:.1f}/min{now}, done'
    seconds = round(remaining * elapsed / completed)
    eta = f'{seconds // 3600}h {seconds % 3600 // 60:02d}m' if seconds >= 3600 else f'{seconds // 60}m {seconds % 60:02d}s'
    return f' | {per_minute:.1f}/min{now}, ETA {eta}'


def terminate_pool(pool):
    # Python 3.11/3.13 have no public terminate_workers API. Capture handles before shutdown.
    workers = list(pool._processes.values())
    if sys.platform == 'win32':
        for worker in workers:
            print(f'stalled/unfinished worker PID {worker.pid}', flush=True)
            try:
                subprocess.run(['tasklist', '/FI', f'PID eq {worker.pid}', '/FO', 'CSV', '/NH'], timeout=10)
            except (OSError, subprocess.TimeoutExpired) as error:
                print(f'process details unavailable: {error}', flush=True)
            try:
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(worker.pid)], capture_output=True, timeout=10)
            except (OSError, subprocess.TimeoutExpired) as error:
                print(f'process-tree kill failed: {error}; falling back to worker termination', flush=True)
    else:
        import signal
        for worker in workers:
            try:
                os.kill(worker.pid, signal.SIGSTOP)  # prevent another child being launched during enumeration
            except ProcessLookupError:
                pass
        snapshot = subprocess.check_output(['ps', '-eo', 'pid=,ppid=,comm='], text=True, timeout=10)
        rows = [line.split(None, 2) for line in snapshot.splitlines()]
        descendants = {worker.pid for worker in workers}
        while True:
            more = {int(pid) for pid, ppid, _ in rows if int(ppid) in descendants} - descendants
            if not more:
                break
            descendants.update(more)
        for worker in workers:
            print(f'stalled/unfinished worker PID {worker.pid}', flush=True)
        for pid, ppid, name in rows:
            if int(pid) in descendants:
                print(f'  PID {pid} parent {ppid}: {name}', flush=True)
        for pid in descendants:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    for worker in workers:
        if worker.is_alive():
            worker.kill()
        worker.join(timeout=5)


def execute(items, db, paths, output, root, command, config, args):
    with tempfile.TemporaryDirectory(prefix='.mutation-workers-', dir=output) as registry:
        pool = concurrent.futures.ProcessPoolExecutor(
            max_workers=args.workers, initializer=prepare_worker, initargs=(str(root), registry))
        unfinished = set()
        finished = False
        # one line per finished mutant (see tools/mutation_times.py); a resumed session adds to it
        times = (output / 'mutation-times.jsonl').open('a' if args.resume else 'w', encoding='utf-8')
        try:
            unfinished = {pool.submit(run_item, item, command, config.timeout) for item in items}
            started = last_result = last_mark = time.monotonic()
            completed = marked = 0
            while unfinished:
                done, unfinished = concurrent.futures.wait(unfinished, timeout=min(1.0, args.stall_timeout),
                                                          return_when=concurrent.futures.FIRST_COMPLETED)
                if not done and time.monotonic() - last_result >= args.stall_timeout:
                    print(f'No progress for {args.stall_timeout:g} s; preserving pending work for --resume', flush=True)
                    return
                for future in done:
                    item, result, seconds = future.result()
                    db.set_result(item.job_id, result)
                    times.write(json.dumps(time_record(item, result, seconds)) + '\n')
                    completed += 1
                    last_result = time.monotonic()
                    if completed % args.progress_every == 0 or not unfinished:
                        times.flush()
                        counts = report(db, paths, output)
                        rate = progress_suffix(completed, len(unfinished), last_result - started,
                                               (completed - marked, last_result - last_mark))
                        marked, last_mark = completed, last_result
                        print(f'{db.num_results}/{db.num_work_items}: {dict(counts)}{rate}', flush=True)
            finished = True
        finally:
            # A context-manager shutdown waits forever for a hung worker: stop the trees first.
            if not finished:
                for future in unfinished:
                    future.cancel()
                terminate_pool(pool)
            pool.shutdown(wait=True, cancel_futures=True)
            times.close()
            for record in Path(registry).glob('*.json'):
                target = Path(json.loads(record.read_text(encoding='utf-8'))['workspace']).resolve()
                if target.parent != Path(tempfile.gettempdir()).resolve() or not target.name.startswith('minimap-mutations-'):
                    raise ValueError(f'Unexpected worker directory: {target}')
                if target.exists():
                    shutil.rmtree(target)
            report(db, paths, output)


def main():
    args = parse_args()
    root = args.project.resolve()
    os.chdir(root)
    output = root / 'dist/ci'
    output.mkdir(parents=True, exist_ok=True)
    config = load_config(str(root / 'cosmic-ray.toml'))
    test_args = shlex.split(config.test_command)
    if not test_args or test_args[0] != 'python':
        raise SystemExit('Mutation test-command must start with python')
    test_args[0] = sys.executable
    command = shlex.join(test_args)
    with session_lock(output):
        paths = [Path(path) for path in selected_modules(list(config['module-path']), args.modules)]
        identity = fingerprint(root, paths)
        session_path = output / 'mutation-session.json'
        if args.resume:
            if not session_path.exists() or json.loads(session_path.read_text(encoding='utf-8')) != json.loads(json.dumps(identity)):
                raise SystemExit('cannot resume: source, tests, configuration or environment changed (or no session metadata)')
        subprocess.run(test_args, check=True, timeout=60)
        mode = WorkDB.Mode.open if args.resume else WorkDB.Mode.create
        with use_db(str(output / 'mutations.sqlite'), mode) as db:
            if not args.resume:
                init(paths, db, config.operators_config)
                write_json(session_path, identity)
            items = list(db.pending_work_items)
            if args.max_results is not None:
                items = items[:args.max_results]
            counts = report(db, paths, output)
            print(f'Running {len(items)} pending mutants using {args.workers} isolated workers', flush=True)
            execute(items, db, paths, output, root, command, config, args)
            counts = report(db, paths, output)
            print(json.dumps(counts, indent=2))
            return 2 if any(t['pending'] or t['error'] for t in counts.values()) else 0


if __name__ == '__main__':
    raise SystemExit(main())
