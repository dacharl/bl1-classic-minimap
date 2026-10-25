"""Write the performance report contract fixtures (docs/research/PERF_REPORT_V1.md).

Usage: python -I tools/make_perf_fixtures.py [out_dir]   (default tools/fixtures/perf_reports)

valid-*.json come from the real profiler, driven against a fake core with a controlled clock, fixed UTC
times and fixed capture IDs, so they are byte-for-byte reproducible. invalid-* each break one rule.
They contain no game data and may be copied into steam-deck-scripts (PLAN_V11_MCP_HANDOFF.md).
"""
import importlib.util
import json
import re
import sys
import tempfile
import tomllib
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / 'tools' / 'fixtures' / 'perf_reports'
MS = 1_000_000
SECOND = 1_000_000_000


def load_profiler():
    spec = importlib.util.spec_from_file_location(
        'mm_profiler_fixtures', ROOT / 'sdk_mods' / 'classic_minimap_profiler' / 'profiler.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


P = load_profiler()


class Clock:
    def __init__(self):
        self.t = 7 * SECOND

    def __call__(self):
        return self.t


def fake_core(clock):
    """Shaped like classic_minimap 0.10.0: tick admits via current_hud_movie, then sends commands."""
    core = types.ModuleType('classic_minimap')
    core.__version__ = tomllib.loads((ROOT / 'sdk_mods/classic_minimap/pyproject.toml').read_text(
        encoding='utf-8'))['project']['version']
    core.costs = {}

    def spend(name):
        clock.t += core.costs.get(name, 0)

    for name in P.WRAPPED:
        setattr(core, name, (lambda n: lambda *a, **k: spend(n))(name))

    def tick(pc):
        spend('tick')
        if pc == 'throttled':
            return
        core.current_hud_movie(pc)
        core.cmd('movie', 'tick', 0.5, 0.5, 90.0)
        core.hidden_reason(pc, 'movie', 0.0)

    def cmd(movie, op, *args):
        spend('cmd.' + op)

    core.tick, core.cmd = tick, cmd
    core.S = types.SimpleNamespace(anchor={'MapFrame': 'Arid'}, threat_source='radar', marks=[0] * 26,
                                   dock_mode='matrix')
    core.zoom_percent = lambda: 185.268496
    core.icon_percent = lambda: 100.0
    core.opt_position = types.SimpleNamespace(value='Docked')
    core.opt_rotate = types.SimpleNamespace(value=False)
    core.mod = types.SimpleNamespace(is_enabled=True, on_disable=lambda: None)
    return core


def profiler(clock, n):
    ids = iter('%032x' % (0xC0FFEE00 + n * 16 + i) for i in range(16))
    out = Path(tempfile.mkdtemp(prefix='mm_fixtures_'))
    return P.Profiler(out_dir=out, log=lambda line: None, clock=clock, new_id=lambda: next(ids),
                      utc=lambda: '2026-10-24T20:%02d:00.000Z' % n)


def startup(core):
    core.start('pc', 'movie')
    core.collect('pc', 'movie')
    core.capture('movie')
    for op in ('clear', 'iconscale', 'scale'):
        core.cmd('movie', op, 100)
    for _ in range(26):
        core.cmd('movie', 'add', 'map.maps.landmarks', 0.4, 0.6, 0.0, 'objective')


def valid_reports():
    reports = {}

    clock = Clock()
    core = fake_core(clock)
    sys.modules['classic_minimap'] = core
    prof = profiler(clock, 1)
    prof.start(60)
    core.costs = {'start': 3 * MS, 'collect': 12 * MS, 'capture': 4 * MS, 'cmd.add': 30_000,
                  'cmd.clear': 80_000, 'cmd.tick': 40_000, 'tick': 60_000, 'hidden_reason': 15_000}
    startup(core)
    for i in range(1200):
        clock.t += 50 * MS
        core.tick('throttled' if i % 4 == 3 else 'pc')
        if i % 10 == 0:
            core.objective_key('pc')
            core.threat_string('pc')
        if i % 20 == 0:
            core.check_dock('movie')
        if prof.state != 'collecting':
            break
    reports['valid-completed'] = prof.report

    clock = Clock()
    core = fake_core(clock)
    sys.modules['classic_minimap'] = core
    prof = profiler(clock, 2)
    prof.start(60)
    clock.t += 2 * SECOND
    reports['valid-empty-metrics'] = prof.stop('stopped_by_user')

    clock = Clock()
    core = fake_core(clock)
    sys.modules['classic_minimap'] = core
    prof = profiler(clock, 3)
    prof.start(300)
    core.costs = {'tick': 90_000, 'collect': 9 * MS}
    for _ in range(40):
        clock.t += 50 * MS
        core.tick('pc')
    core.collect('pc', 'movie')
    ours = core.collect
    core.collect = lambda *a, **k: ours(*a, **k)     # another mod wraps the profiler's wrapper
    clock.t += SECOND
    reports['valid-aborted-detach-conflict'] = prof.stop('stopped_by_user')

    clock = Clock()
    core = fake_core(clock)
    sys.modules['classic_minimap'] = core
    prof = profiler(clock, 4)
    prof.start(60)
    core.costs = {'tick': 70_000}
    for _ in range(98):
        clock.t += 50 * MS
        core.tick('pc')
    core.costs = {'tick': 1500 * MS, 'rebuild_in_place': 1400 * MS}
    core.rebuild_in_place('pc', 'movie')
    core.tick('pc')
    core.tick('pc')
    reports['valid-overflow'] = prof.stop('stopped_by_user')

    clock = Clock()
    core = fake_core(clock)
    sys.modules['classic_minimap'] = core
    prof = profiler(clock, 5)
    prof.start(120)
    core.costs = {'tick': 55_000, 'cmd.tick': 35_000, 'cmd.threats': 120_000, 'threat_string': 200_000}
    startup(core)
    while prof.state == 'collecting':
        clock.t += 50 * MS
        core.tick('pc')
        core.cmd('movie', 'threats', '')
        core.threat_string('pc')
    reports['valid-120s'] = prof.report
    sys.modules.pop('classic_minimap', None)
    return reports


def edited(report, change):
    copy = json.loads(json.dumps(report))
    change(copy)
    return P.serialize(copy)


def invalid_files(base):
    def set_path(*path_and_value):
        *path, value = path_and_value

        def change(r):
            target = r
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
        return change

    def delete(*path):
        def change(r):
            target = r
            for key in path[:-1]:
                target = target[key]
            del target[path[-1]]
        return change

    def bucket_mismatch(r):
        r['timings']['tick']['buckets'][0] += 1

    def deep(r):
        nested = 'inclusive_spans'
        for _ in range(15):
            nested = [nested]
        r['limitations'] = [nested]                   # depth 17 at the innermost string

    text = P.serialize(base)
    files = {
        'invalid-wrong-provider.json': edited(base, set_path('provider_id', 'bl1-minimap')),
        'invalid-wrong-game.json': edited(base, set_path('game', 'app_id', 729040)),
        'invalid-unlisted-version.json': edited(base, set_path('producer', 'version', '9.9.9')),
        'invalid-schema-v2.json': edited(base, set_path('schema_version', 2)),
        'invalid-long-string.json': edited(base, set_path('context', 'map_frame', 'x' * 97)),
        'invalid-unknown-key.json': edited(base, set_path('capture', 'session', 'extra')),
        'invalid-bucket-sum.json': edited(base, bucket_mismatch),
        'invalid-failed-gt-count.json': edited(base, set_path('timings', 'collect', 'failed', 2)),
        'invalid-negative-counter.json': edited(base, set_path('counters', 'rebuilds', -1)),
        'invalid-unknown-limitation.json': edited(base, set_path('limitations', ['inclusive_spans', 'fast'])),
        'invalid-state-reason.json': edited(base, set_path('capture', 'state', 'aborted')),
        'invalid-missing-field.json': edited(base, delete('capture', 'requested_seconds')),
        'invalid-depth-17.json': edited(base, deep),
        # Raw edits that json.dumps cannot produce:
        'invalid-duplicate-key.json': text.replace('"schema_version": 1,', '"schema_version": 1,\n "schema_version": 1,', 1),
        'invalid-nan.json': re.sub(r'"elapsed_seconds": [0-9.e+-]+', '"elapsed_seconds": NaN', text, count=1),
        'invalid-oversized.json': text[:-2] + ' ' * (P.REPORT_LIMIT + 1 - len(text)) + text[-2:],
    }
    assert '"schema_version": 1,\n "schema_version"' in files['invalid-duplicate-key.json']
    assert 'NaN' in files['invalid-nan.json']
    return files


def build(out=DEFAULT_OUT):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    reports = valid_reports()
    written = {f'{name}.json': P.serialize(report) for name, report in reports.items()}
    written.update(invalid_files(reports['valid-completed']))
    for name, text in written.items():
        (out / name).write_bytes(text.encode('utf-8'))
    return sorted(written)


if __name__ == '__main__':
    for name in build(*sys.argv[1:]):
        print(name)
