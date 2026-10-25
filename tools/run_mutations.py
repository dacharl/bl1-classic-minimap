"""Run every Cosmic Ray mutant in isolated source copies, with no game assets.

Usage: python -I tools/run_mutations.py [--workers auto|N]
All outcomes, including timeouts and tool failures, remain in the denominator.
"""
import argparse
import concurrent.futures
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
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


def prepare_worker(root):
    global WORKSPACE
    # One finalizer owns cleanup. TemporaryDirectory's weakref finalizer can run
    # before multiprocessing finalizers on Python 3.13, while cwd is still here.
    WORKSPACE = tempfile.mkdtemp(prefix='minimap-mutations-')
    Finalize(None, cleanup_worker, args=(root,), exitpriority=10)
    target = Path(WORKSPACE)
    for folder in ('tools', 'sdk_mods'):
        shutil.copytree(Path(root) / folder, target / folder,
                        ignore=shutil.ignore_patterns('__pycache__', 'pk', '*.pyc', '*.pyo'))
    os.chdir(target)


def run_item(item, command, timeout):
    result = mutate_and_test(item.mutations, command, timeout)
    return item, result


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=worker_count, default='auto',
                        help='auto (available CPUs) or a positive integer')
    parser.add_argument('--modules', nargs='+', default=[],
                        help='run only these configured module paths (local measurement; CI runs all)')
    args = parser.parse_args(argv)
    if sys.platform == 'win32' and args.workers > 61:
        args.workers = 61  # ProcessPoolExecutor's Windows handle limit.
    return args


def selected_modules(configured, wanted):
    """The configured module paths, optionally narrowed to `wanted` (configured order kept)."""
    unknown = set(wanted) - set(configured)
    if unknown:
        raise SystemExit(f'Not in cosmic-ray.toml module-path: {", ".join(sorted(unknown))}')
    return [path for path in configured if not wanted or path in wanted]


def main():
    args = parse_args()
    os.chdir(ROOT)
    output = ROOT / 'dist/ci'
    output.mkdir(parents=True, exist_ok=True)
    config = load_config(str(ROOT / 'cosmic-ray.toml'))
    test_args = shlex.split(config.test_command)
    if not test_args or test_args[0] != 'python':
        raise SystemExit('Mutation test-command must start with python')
    test_args[0] = sys.executable
    command = shlex.join(test_args)
    # Establish a passing unmutated run; import/environment failures cannot fake kills.
    subprocess.run(test_args, check=True, timeout=60)
    counts = {}
    survivors = []
    with use_db(str(output / 'mutations.sqlite'), WorkDB.Mode.create) as db:
        paths = [Path(path) for path in selected_modules(list(config['module-path']), args.modules)]
        init(paths, db, config.operators_config)
        items = list(db.pending_work_items)
        for path in paths:
            counts[path.as_posix()] = Counter(total=0, killed=0, survived=0, timeout=0, error=0, pending=0)
        print(f'Running all {len(items)} mutants using {args.workers} isolated workers', flush=True)
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=args.workers, initializer=prepare_worker, initargs=(str(ROOT),),
        ) as pool:
            futures = [pool.submit(run_item, item, command, config.timeout) for item in items]
            for completed, future in enumerate(concurrent.futures.as_completed(futures), 1):
                item, result = future.result()
                db.set_result(item.job_id, result)
                name = item.mutations[0].module_path.as_posix()
                tally = counts[name]
                tally['total'] += 1
                if result.worker_outcome != 'normal' or result.test_outcome not in {'killed', 'survived'}:
                    outcome = 'error'
                elif result.output == 'timeout':
                    outcome = 'timeout'
                else:
                    outcome = result.test_outcome.value
                tally[outcome] += 1
                if outcome != 'killed':
                    survivors.append({'module': name, 'outcome': outcome, 'diff': result.diff,
                                      'output': result.output})
                if completed % 50 == 0 or completed == len(items):
                    print(f'{completed}/{len(items)}: {dict(counts)}', flush=True)
    (output / 'mutations.json').write_text(json.dumps(counts, indent=2), encoding='utf-8')
    (output / 'mutation-survivors.json').write_text(json.dumps(survivors, indent=2), encoding='utf-8')
    print(json.dumps(counts, indent=2))


if __name__ == '__main__':
    main()
