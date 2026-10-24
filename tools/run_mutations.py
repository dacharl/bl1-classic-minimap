"""Run every Cosmic Ray mutant in isolated source copies, with no game assets.

Usage: python -I tools/run_mutations.py [--workers 4]
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
WORKSPACE = None


def cleanup_worker(root):
    # Windows cannot remove a directory while it is the process's working directory.
    os.chdir(root)
    if WORKSPACE is not None:
        WORKSPACE.cleanup()


def prepare_worker(root):
    global WORKSPACE
    WORKSPACE = tempfile.TemporaryDirectory(prefix='minimap-mutations-')
    Finalize(None, cleanup_worker, args=(root,), exitpriority=10)
    target = Path(WORKSPACE.name)
    for folder in ('tools', 'sdk_mods'):
        shutil.copytree(Path(root) / folder, target / folder,
                        ignore=shutil.ignore_patterns('__pycache__', 'pk', '*.pyc', '*.pyo'))
    os.chdir(target)


def run_item(item, command, timeout):
    result = mutate_and_test(item.mutations, command, timeout)
    return item, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=int, default=min(4, os.cpu_count() or 1))
    args = parser.parse_args()
    if args.workers < 1:
        parser.error('--workers must be positive')
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
        paths = [Path(path) for path in config['module-path']]
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
