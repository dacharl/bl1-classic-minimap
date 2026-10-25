"""Local overhead benchmark for the optional profiler (PLAN_V11 step 5, decision 8). Not run in CI.

Usage: python -I tools/bench_profiler.py [movie.gfx] [--rounds N]

Each round runs the real core scenario (test_minimap_mod.main, game stubs) twice in fresh processes, once
detached and once with a capture attached, alternating which goes first. An external perf_counter_ns
clock wraps the full registered PlayerTick hook, so the measurement includes the profiler's own wrappers.
Reports per-hook-call p50/p95 for both conditions, the incremental p95, and the collector's memory
(tracemalloc: allocations made by start() plus growth while capturing). Release requirements: incremental
p95 under 0.05 ms per admitted update and collector state under 64 KiB. Timings depend on this machine and
the stubs; they are evidence for the requirement, not a measurement of the game.

The p95 requirement is judged on paired increments (the deterministic scenario run twice with attach and
detach alternating per hook call, parity swapped). If the paired noise floor is wider than the limit the
result is "unresolved" (exit 2), never a pass. Exit 1 means a requirement was not met.
"""
import argparse
import contextlib
import io
import json
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
HOOK = 'WillowGame.WillowPlayerController:PlayerTick'
P95_LIMIT_MS = 0.05
MEMORY_LIMIT = 64 * 1024


def percentile(values, p):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, -(-p * len(ordered) // 100) - 1))]


def child(movie, attached, trace_memory=False):
    """One scenario run. tracemalloc slows every allocation, so memory is measured in separate runs
    (trace_memory) and timing runs are never traced."""
    import test_minimap_mod
    durations, memory = [], {}

    def on_import(core):
        registered = test_minimap_mod.HOOKS[HOOK]

        def timed(*args):
            t0 = time.perf_counter_ns()
            try:
                return registered(*args)
            finally:
                durations.append(time.perf_counter_ns() - t0)

        test_minimap_mod.HOOKS[HOOK] = timed
        if attached:
            sys.path.insert(0, str(ROOT / 'sdk_mods' / 'classic_minimap_profiler'))
            import profiler
            core.mod.is_enabled = True
            prof = profiler.Profiler(out_dir=Path(tempfile.mkdtemp(prefix='mm_bench_')), log=lambda line: None)
            if trace_memory:
                tracemalloc.start()
                memory['before'] = tracemalloc.take_snapshot()
            assert prof.start(300) == 'collecting'
            memory['prof'] = prof

    with contextlib.redirect_stdout(io.StringIO()):
        test_minimap_mod.main(movie, on_import=on_import)
    result = {'durations_ns': durations}
    if attached and not trace_memory:
        report = memory['prof'].stop('stopped_by_user')
        timed = sum(t['count'] for name, t in report['timings'].items() if name not in ('tick', 'tick_admitted'))
        # every tick is wrapped too, plus current_hud_movie once per admitted tick
        result['wrapped_calls'] = timed + report['counters']['ticks_total'] + report['counters']['ticks_admitted']
        result['admitted'] = report['counters']['ticks_admitted']
    if trace_memory:
        filters = [tracemalloc.Filter(True, str(ROOT / 'sdk_mods' / 'classic_minimap_profiler' / '*'))]
        after = tracemalloc.take_snapshot().filter_traces(filters)
        grown = after.compare_to(memory['before'].filter_traces(filters), 'filename')
        result['collector_bytes'] = sum(stat.size_diff for stat in grown)
        tracemalloc.stop()
    print(json.dumps(result))


def paired_child(movie, parity):
    """Hook call i runs attached when i % 2 == parity, detached otherwise. Attach (start) and detach
    (reset, nothing saved) happen outside the timed region, so the clock sees only the wrappers' cost.
    The scenario is deterministic: running both parities measures every hook call in both conditions."""
    import test_minimap_mod
    durations = []

    def on_import(core):
        registered = test_minimap_mod.HOOKS[HOOK]
        sys.path.insert(0, str(ROOT / 'sdk_mods' / 'classic_minimap_profiler'))
        import profiler
        core.mod.is_enabled = True
        prof = profiler.Profiler(out_dir=Path(tempfile.mkdtemp(prefix='mm_bench_')), log=lambda line: None)

        def timed(*args):
            attach = len(durations) % 2 == parity
            if attach and prof.state != 'collecting':
                prof.start(300)
            elif not attach and prof.state == 'collecting':
                prof.reset()
            t0 = time.perf_counter_ns()
            try:
                return registered(*args)
            finally:
                durations.append(time.perf_counter_ns() - t0)

        test_minimap_mod.HOOKS[HOOK] = timed

    with contextlib.redirect_stdout(io.StringIO()):
        test_minimap_mod.main(movie, on_import=on_import)
    print(json.dumps({'durations_ns': durations}))


def wrapper_cost_ns(calls=200_000):
    """Median extra ns one timed wrapper adds to a no-op call (5 alternating batches)."""
    import types
    sys.path.insert(0, str(ROOT / 'sdk_mods' / 'classic_minimap_profiler'))
    import profiler
    core = types.ModuleType(profiler.CORE_MODULE)
    core.__version__ = profiler.SUPPORTED_CORE_VERSIONS[0]
    for name in profiler.WRAPPED:
        setattr(core, name, lambda *a, **k: None)
    core.mod = types.SimpleNamespace(is_enabled=True)
    saved = sys.modules.get(profiler.CORE_MODULE)
    sys.modules[profiler.CORE_MODULE] = core
    prof = profiler.Profiler(out_dir=Path(tempfile.mkdtemp(prefix='mm_bench_')), log=lambda line: None)

    def batch():
        fn = core.get_num
        t0 = time.perf_counter_ns()
        for _ in range(calls):
            fn('movie', 'path')
        return (time.perf_counter_ns() - t0) / calls

    diffs = []
    for _ in range(5):
        plain = batch()
        prof.start(300)
        wrapped = batch()
        prof.reset()
        diffs.append(wrapped - plain)
    if saved is not None:
        sys.modules[profiler.CORE_MODULE] = saved
    else:
        sys.modules.pop(profiler.CORE_MODULE)
    return statistics.median(diffs)


def run_child(movie, mode):
    out = subprocess.run([sys.executable, '-B', '-I', __file__, movie, '--child', mode],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('movie', nargs='?', default=str(ROOT / 'dist/phase2/HUD_minimap.gfx'))
    parser.add_argument('--rounds', type=int, default=6)
    parser.add_argument('--child', choices=['attached', 'detached', 'memory', 'paired0', 'paired1'],
                        help=argparse.SUPPRESS)
    args = parser.parse_args()
    movie = args.movie
    if not Path(movie).exists():
        from ci_fixture import build_fixture
        synthetic = Path(tempfile.mkdtemp(prefix='mm_bench_')) / 'synthetic.gfx'
        synthetic.write_bytes(build_fixture())
        movie = str(synthetic)
    if args.child in ('paired0', 'paired1'):
        paired_child(movie, int(args.child[-1]))
        return 0
    if args.child:
        child(movie, args.child != 'detached', trace_memory=args.child == 'memory')
        return 0
    run_child(movie, 'detached')                 # warm-up (file cache, imports)
    run_child(movie, 'attached')
    samples = {False: [], True: []}
    calls = admitted = 0
    for i in range(args.rounds):
        for attached in ((False, True) if i % 2 == 0 else (True, False)):
            result = run_child(movie, 'attached' if attached else 'detached')
            samples[attached] += result['durations_ns']
            calls += result.get('wrapped_calls', 0)
            admitted += result.get('admitted', 0)
    memory = [run_child(movie, 'memory')['collector_bytes'] for _ in range(2)]
    per_call_ns = wrapper_cost_ns()
    # Paired: for each hook call index, attached minus detached duration from runs of opposite parity.
    increments = []
    for i in range(args.rounds):
        runs = {p: run_child(movie, f'paired{p}')['durations_ns'] for p in ((0, 1) if i % 2 == 0 else (1, 0))}
        for k, (a0, a1) in enumerate(zip(runs[0], runs[1])):
            attached, detached = (a0, a1) if k % 2 == 0 else (a1, a0)
            increments.append((attached - detached) / 1_000_000)
    ms = {k: [d / 1_000_000 for d in v] for k, v in samples.items()}
    report = {'movie': movie, 'rounds': args.rounds, 'hook_calls_per_condition': len(ms[False]),
              'detached_p50_ms': statistics.median(ms[False]), 'detached_p95_ms': percentile(ms[False], 95),
              'attached_p50_ms': statistics.median(ms[True]), 'attached_p95_ms': percentile(ms[True], 95),
              'collector_bytes_max': max(memory)}
    report['incremental_p95_ms'] = report['attached_p95_ms'] - report['detached_p95_ms']
    report['incremental_p50_ms'] = report['attached_p50_ms'] - report['detached_p50_ms']
    # Low-noise corroboration: one wrapper's cost times the wrapped calls an admitted update makes.
    report['wrapper_ns_per_call'] = per_call_ns
    report['wrapped_calls_per_admitted_update'] = calls / admitted if admitted else None
    report['estimated_ms_per_admitted_update'] = (per_call_ns * calls / admitted / 1_000_000) if admitted else None
    report['paired_samples'] = len(increments)
    report['paired_increment_p50_ms'] = statistics.median(increments)
    report['paired_increment_p95_ms'] = percentile(increments, 95)
    report['paired_increment_p05_ms'] = percentile(increments, 5)     # spread of the noise below zero
    # Decision 8 is judged on the paired per-call increment. When the paired noise floor (how far the
    # increments fall below zero, where the true overhead cannot be) is wider than the limit, this harness
    # cannot decide the requirement: report "unresolved" instead of passing or failing it.
    if report['paired_increment_p05_ms'] < -P95_LIMIT_MS:
        report['p95_requirement'] = 'unresolved'
    else:
        report['p95_requirement'] = 'met' if report['paired_increment_p95_ms'] < P95_LIMIT_MS else 'not_met'
    report['memory_requirement_met'] = report['collector_bytes_max'] < MEMORY_LIMIT
    print(json.dumps(report, indent=1))
    if not report['memory_requirement_met'] or report['p95_requirement'] == 'not_met':
        return 1
    return 2 if report['p95_requirement'] == 'unresolved' else 0


if __name__ == '__main__':
    raise SystemExit(main())
