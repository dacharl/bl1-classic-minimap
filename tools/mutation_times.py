"""Where a mutation run spent its time: totals per file and per operator, and the slowest mutants.

Usage: python -I tools/mutation_times.py [dist/ci/mutation-times.jsonl] [--slowest N]
run_mutations.py writes one line per finished mutant (seconds are wall time of the mutate-and-test step, which
includes starting the suites). A mutant is slow when it survives (it runs its whole suite list) or hangs.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(path):
    """The records of a times file; blank lines are skipped."""
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def _totals(rows, key):
    groups = {}
    for row in rows:
        groups.setdefault(row[key], []).append(row)
    return groups


def summarize(rows, slowest=15):
    """{'files': per file (largest total first), 'operators': per operator, 'slowest': the slowest mutants}."""
    files = []
    for name, group in _totals(rows, 'file').items():
        seconds = sum(r['seconds'] for r in group)
        files.append(dict(name=name, count=len(group), seconds=seconds, mean=seconds / len(group),
                          max=max(r['seconds'] for r in group),
                          survived=sum(1 for r in group if r.get('outcome') != 'killed')))
    operators = []
    for name, group in _totals(rows, 'operator').items():
        seconds = sum(r['seconds'] for r in group)
        operators.append(dict(name=name, count=len(group), seconds=seconds, mean=seconds / len(group)))
    return dict(files=sorted(files, key=lambda f: -f['seconds']),
                operators=sorted(operators, key=lambda o: -o['seconds']),
                slowest=sorted(rows, key=lambda r: -r['seconds'])[:slowest])


def render(summary):
    """The summary as text."""
    out = ['Per file (total seconds of worker time; divide by the worker count for wall time):']
    for f in summary['files']:
        out.append(f"  {f['seconds']:9.0f} s  {f['count']:6d} mutants  mean {f['mean']:5.2f} s  max {f['max']:6.1f} s"
                   f"  not killed {f['survived']:5d}  {f['name']}")
    out.append('Per operator:')
    for o in summary['operators']:
        out.append(f"  {o['seconds']:9.0f} s  {o['count']:6d} mutants  mean {o['mean']:5.2f} s  {o['name']}")
    out.append('Slowest mutants:')
    for r in summary['slowest']:
        out.append(f"  {r['seconds']:7.1f} s  {r.get('outcome')}  {r['file']}  {r['operator']} #{r['occurrence']}")
    return '\n'.join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', nargs='?', type=Path, default=ROOT / 'dist/ci/mutation-times.jsonl')
    parser.add_argument('--slowest', type=int, default=15)
    args = parser.parse_args(argv)
    print(render(summarize(load(args.log), args.slowest)))


if __name__ == '__main__':
    main()
