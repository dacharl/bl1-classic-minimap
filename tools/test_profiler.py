"""Tests for the optional profiler add-on (PLAN_V11).

Usage: python -I tools/test_profiler.py

Unit cases drive profiler.py against a fake core module with a controlled duration clock. The
integration case runs the real core scenario (test_minimap_mod.main on the synthetic CI movie) with a
capture attached throughout: every core assertion must still hold, and the wrappers must see real calls.
"""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PROFILER_DIR = ROOT / 'sdk_mods' / 'classic_minimap_profiler'
CORE_DIR = ROOT / 'sdk_mods' / 'classic_minimap'
sys.path.insert(0, str(HERE))

MS = 1_000_000          # ns per ms


def load_profiler():
    """profiler.py as a standalone module: it must not need unrealsdk or mods_base."""
    spec = importlib.util.spec_from_file_location('mm_profiler_under_test', PROFILER_DIR / 'profiler.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


P = load_profiler()


class Clock:
    def __init__(self):
        self.t = 5_000_000_000

    def __call__(self):
        return self.t


def fake_core(clock, version='0.10.0', enabled=True):
    """A core module shaped like classic_minimap: tick admits after its throttle via current_hud_movie."""
    core = types.ModuleType('classic_minimap')
    core.__version__ = version
    core.costs = {}                 # function name -> ns spent inside, simulated with the clock
    core.calls = []
    core.throttled = False

    def spend(name):
        core.calls.append(name)
        clock.t += core.costs.get(name, 0)

    def current_hud_movie(pc):
        spend('current_hud_movie')
        return 'movie'

    def cmd(movie, op, *args):
        spend('cmd')
        if op == 'boom':
            raise RuntimeError('movie failed')

    def tick(pc):
        spend('tick')
        if core.throttled:
            return None
        core.current_hud_movie(pc)
        core.cmd('movie', 'tick', 1.0)
        return 'ticked'

    for name in P.WRAPPED:
        if not hasattr(core, name):
            setattr(core, name, (lambda n: lambda *a, **k: spend(n))(name))
    core.current_hud_movie, core.cmd, core.tick = current_hud_movie, cmd, tick
    core.S = types.SimpleNamespace(anchor={'MapFrame': 'Arid'}, threat_source='radar', marks=[1, 2, 3],
                                   dock_mode='matrix', fit=185.27)
    core.zoom_percent = lambda: 185.27
    core.icon_percent = lambda: 100.0
    core.opt_position = types.SimpleNamespace(value='Docked')
    core.opt_rotate = types.SimpleNamespace(value=False)
    core.mod = types.SimpleNamespace(is_enabled=enabled, on_enable=lambda: None, on_disable=lambda: None)
    return core


class Base(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.core = fake_core(self.clock)
        sys.modules['classic_minimap'] = self.core
        self.dir = tempfile.TemporaryDirectory()
        self.out = Path(self.dir.name) / 'reports'
        self.logs = []
        self.prof = P.Profiler(clock=self.clock, out_dir=self.out, log=self.logs.append,
                               utc=lambda: '2026-10-24T20:00:00.000Z')

    def tearDown(self):
        sys.modules.pop('classic_minimap', None)
        self.dir.cleanup()


class AggregationChecks(unittest.TestCase):
    def test_literal_statistics(self):
        s = P.Stats()
        for ms in (0.1, 0.2, 0.4):
            s.record(int(ms * MS), True)
        d = s.as_dict()
        self.assertEqual(d['count'], 3)
        self.assertEqual(d['failed'], 0)
        self.assertAlmostEqual(d['total_ms'], 0.7, places=9)
        self.assertAlmostEqual(d['mean_ms'], 0.233333, places=6)
        self.assertAlmostEqual(d['max_ms'], 0.4, places=9)
        self.assertEqual(d['p95_le_ms'], 0.5)
        self.assertEqual(d['p50_le_ms'], 0.2)
        self.assertEqual(sum(d['buckets']), 3)
        self.assertEqual(len(d['buckets']), 16)

    def test_empty_metric_is_null_not_zero(self):
        d = P.Stats().as_dict()
        self.assertEqual((d['count'], d['failed'], d['buckets']), (0, 0, [0] * 16))
        for key in ('total_ms', 'mean_ms', 'max_ms', 'p50_le_ms', 'p95_le_ms', 'p99_le_ms'):
            self.assertIsNone(d[key])

    def test_bucket_boundaries_and_overflow(self):
        s = P.Stats()
        s.record(int(0.5 * MS), True)          # exactly on a bound: that bucket
        s.record(1500 * MS, False)             # overflow, failed
        d = s.as_dict()
        self.assertEqual(d['buckets'][5], 1)
        self.assertEqual(d['buckets'][15], 1)
        self.assertEqual(d['failed'], 1)
        self.assertEqual(d['p50_le_ms'], 0.5)
        self.assertIsNone(d['p99_le_ms'])      # overflow has no upper bound
        self.assertAlmostEqual(d['max_ms'], 1500.0)


class LifecycleChecks(Base):
    def test_refuses_missing_disabled_and_unsupported_cores(self):
        sys.modules.pop('classic_minimap')
        self.assertEqual(self.prof.start(60), 'core_missing')
        sys.modules['classic_minimap'] = fake_core(self.clock, enabled=False)
        self.assertEqual(self.prof.start(60), 'core_disabled')
        sys.modules['classic_minimap'] = fake_core(self.clock, version='0.9.0')
        self.assertEqual(self.prof.start(60), 'unsupported_version')
        self.assertEqual(self.prof.state, 'idle')

    def test_wrappers_exist_only_during_a_capture(self):
        originals = {name: getattr(self.core, name) for name in P.WRAPPED}
        self.assertEqual(self.prof.start(60), 'collecting')
        self.assertEqual(self.prof.start(60), 'already_collecting')
        for name in P.WRAPPED:
            self.assertIsNot(getattr(self.core, name), originals[name], name)
        self.prof.stop('stopped_by_user')
        for name in P.WRAPPED:
            self.assertIs(getattr(self.core, name), originals[name], name)
        self.assertEqual(self.prof.state, 'stopped')

    def test_pass_through_values_errors_and_order(self):
        self.prof.start(60)
        self.assertEqual(self.core.tick('pc'), 'ticked')
        with self.assertRaises(RuntimeError):
            self.core.cmd('movie', 'boom')
        self.assertEqual(self.core.calls, ['tick', 'current_hud_movie', 'cmd', 'cmd'])
        report = self.prof.stop('stopped_by_user')
        self.assertEqual(report['timings']['cmd.other']['failed'], 1)
        self.assertEqual(report['timings']['cmd.tick']['count'], 1)

    def test_admission_and_inclusive_spans(self):
        self.core.costs = {'tick': 1_500_000, 'cmd': 500_000}
        self.prof.start(60)
        self.core.tick('pc')                    # admitted: 2.0 ms including a 0.5 ms command
        self.core.throttled = True
        self.core.tick('pc')                    # throttled: 1.5 ms, not admitted
        report = self.prof.stop('stopped_by_user')
        t = report['timings']
        self.assertEqual(t['tick']['count'], 2)
        self.assertEqual(t['tick_admitted']['count'], 1)
        self.assertAlmostEqual(t['tick_admitted']['max_ms'], 2.0)
        self.assertAlmostEqual(t['cmd.tick']['total_ms'], 0.5)
        self.assertAlmostEqual(t['tick']['total_ms'], 3.5)   # inclusive, never tick + cmd
        self.assertEqual(report['counters']['ticks_total'], 2)
        self.assertEqual(report['counters']['ticks_admitted'], 1)
        self.assertIn('inclusive_spans', report['limitations'])

    def test_detach_conflict_leaves_a_later_wrapper_alone(self):
        self.prof.start(60)
        ours = self.core.collect
        later = lambda *a, **k: ours(*a, **k)   # noqa: E731  another mod wraps our wrapper
        self.core.collect = later
        report = self.prof.stop('stopped_by_user')
        self.assertIs(self.core.collect, later)
        self.assertEqual(report['capture']['state'], 'aborted')
        self.assertEqual(report['capture']['save_reason'], 'detach_conflict')
        self.assertIn('detach_conflict', report['limitations'])
        self.assertEqual(self.prof.conflicts, ['collect'])
        self.assertTrue(any('restart' in line for line in self.logs))

    def test_core_disable_aborts_and_restores(self):
        original_disable, original_tick = self.core.mod.on_disable, self.core.tick
        self.prof.start(60)
        self.core.mod.on_disable()              # mods_base calls the field on the mod object
        self.assertEqual(self.prof.state, 'stopped')
        self.assertEqual(self.prof.report['capture']['save_reason'], 'core_disabled')
        self.assertIs(self.core.mod.on_disable, original_disable)
        self.assertIs(self.core.tick, original_tick)

    def test_replaced_core_module_is_unsupported_lifecycle(self):
        self.prof.start(60)
        sys.modules['classic_minimap'] = fake_core(self.clock)
        report = self.prof.dump()
        self.assertEqual(report['capture']['save_reason'], 'unsupported_lifecycle')
        self.assertEqual(report['capture']['state'], 'aborted')

    def test_capture_length_and_idle_stop(self):
        with self.assertRaises(ValueError):
            self.prof.start(45)
        self.assertIsNone(self.prof.stop('stopped_by_user'))
        self.assertIsNone(self.prof.dump())
        self.assertEqual(self.logs, ['[Classic Minimap Profiler] no capture to report yet'])

    def test_nesting_beyond_the_depth_cap_is_called_but_not_timed(self):
        depth = {'n': 0}

        def collect(*args):
            depth['n'] += 1
            if depth['n'] < P.MAX_DEPTH + 5:
                self.core.collect()
            return depth['n']

        self.core.collect = collect
        self.prof.start(60)
        self.assertEqual(self.core.collect(), P.MAX_DEPTH + 5)
        report = self.prof.stop('stopped_by_user')
        self.assertEqual(report['timings']['collect']['count'], P.MAX_DEPTH)

    def test_unreadable_or_non_finite_context_is_null(self):
        self.core.S.anchor = None                  # .get fails
        self.core.zoom_percent = lambda: float('inf')
        self.core.S.threat_source = 'x' * 200
        self.prof.start(60)
        context = self.prof.stop('stopped_by_user')['context']
        self.assertIsNone(context['map_frame'])
        self.assertIsNone(context['zoom_final'])
        self.assertEqual(len(context['threat_source']), 96)

    def test_in_place_reload_is_unsupported_lifecycle(self):
        """importlib.reload re-runs the module in the same object: new functions and a new mod object."""
        self.prof.start(60)
        reloaded = fake_core(self.clock)
        new_tick = reloaded.tick
        self.core.tick, self.core.mod = new_tick, reloaded.mod
        report = self.prof.dump()
        self.assertEqual(report['capture']['save_reason'], 'unsupported_lifecycle')
        self.assertIn('unsupported_lifecycle', report['limitations'])
        self.assertIs(self.core.tick, new_tick)    # the reloaded function is left alone

    def test_reset_discards_without_saving(self):
        self.prof.start(60)
        self.core.tick('pc')
        self.prof.reset()
        self.assertEqual(self.prof.state, 'idle')
        self.assertIsNone(self.prof.report)
        self.assertFalse(self.out.exists())


class CaptureChecks(Base):
    def test_timed_capture_stops_and_saves_once(self):
        self.core.costs = {'tick': 1 * MS}
        original_tick = self.core.tick
        self.assertEqual(self.prof.start(30), 'collecting')
        self.assertFalse(self.out.exists(), 'no writes during the measurement window')
        self.clock.t += 29 * 1_000_000_000
        self.core.tick('pc')
        self.assertEqual(self.prof.state, 'collecting')
        self.clock.t += 2 * 1_000_000_000
        self.core.tick('pc')                    # crosses 30 s: stop, detach, save
        self.assertEqual(self.prof.state, 'stopped')
        self.assertIs(self.core.tick, original_tick)
        data = json.loads((self.out / P.REPORT_NAME).read_text(encoding='utf-8'))
        cap = data['capture']
        self.assertEqual((cap['state'], cap['save_reason'], cap['complete']), ('stopped', 'completed', True))
        self.assertEqual(cap['requested_seconds'], 30)
        self.assertGreaterEqual(cap['elapsed_seconds'], 30.0)
        self.assertRegex(cap['id'], r'^[0-9a-f]{32}$')
        self.assertEqual(data['counters']['publications'], 1)
        self.assertTrue((self.out / P.SUMMARY_NAME).read_text(encoding='utf-8').startswith('Classic Minimap'))

    def test_capture_id_source_is_injectable(self):
        prof = P.Profiler(clock=self.clock, out_dir=self.out, log=self.logs.append, utc=lambda: 'T',
                          new_id=lambda: '0' * 32)
        prof.start(60)
        self.assertEqual(prof.stop('stopped_by_user')['capture']['id'], '0' * 32)

    def test_report_matches_contract_and_bounds(self):
        self.prof.start(60)
        self.core.tick('pc')
        report = self.prof.stop('stopped_by_user')
        self.assertEqual(set(report), {'schema_version', 'provider_id', 'game', 'producer', 'capture', 'summary',
                                       'timings', 'counters', 'context', 'limitations'})
        self.assertEqual(report['provider_id'], 'bl1-classic-minimap-performance')
        self.assertEqual(report['game'], {'app_id': 8980, 'slug': 'borderlands-1-goty-classic',
                                          'edition': 'Borderlands 1 GOTY Classic'})
        self.assertEqual(report['producer'], {'name': 'classic_minimap_profiler', 'version': P.PROFILER_VERSION,
                                              'core_version': '0.10.0'})
        self.assertEqual(set(report['timings']), set(P.METRICS))
        self.assertEqual(report['context']['map_frame'], 'Arid')
        self.assertEqual(report['context']['markers'], 3)
        self.assertTrue(set(report['limitations']) <= set(P.LIMITATIONS))
        raw = json.dumps(report, allow_nan=False).encode()
        self.assertLessEqual(len(raw), P.REPORT_LIMIT)
        self.assertFalse(report['capture']['complete'])

    def test_archive_rotation_keeps_eight(self):
        for n in range(10):
            self.prof.start(60)
            self.prof.stop('stopped_by_user')
        slots = sorted(p.name for p in (self.out / 'archive').iterdir())
        self.assertEqual(slots, ['slot-%d' % i for i in range(1, 9)])
        ids = [json.loads((self.out / 'archive' / ('slot-%d' % i) / P.REPORT_NAME).read_text())['capture']['id']
               for i in range(1, 9)]
        latest = json.loads((self.out / P.REPORT_NAME).read_text())['capture']['id']
        self.assertEqual(len(set(ids + [latest])), 9)

    def test_failed_publication_keeps_last_good_file(self):
        self.prof.start(60)
        self.prof.stop('stopped_by_user')
        good = (self.out / P.REPORT_NAME).read_bytes()
        self.prof.start(60)
        self.prof.write_text = lambda path, text: (_ for _ in ()).throw(OSError('disk full'))
        self.prof.stop('stopped_by_user')
        self.assertEqual((self.out / P.REPORT_NAME).read_bytes(), good)
        self.assertTrue(any('not saved' in line for line in self.logs))

    def test_dump_logs_one_record_and_does_not_reset(self):
        self.prof.start(60)
        self.core.tick('pc')
        report = self.prof.dump()
        self.assertEqual(report['capture']['save_reason'], 'stopped_by_user')
        records = [line for line in self.logs if line.startswith(P.LOG_PREFIX)]
        self.assertEqual(len(records), 1)
        self.assertEqual(json.loads(records[0][len(P.LOG_PREFIX):])['capture']['id'], report['capture']['id'])
        again = self.prof.dump()                  # stopped: logs the same report, no new capture
        self.assertEqual(again['capture']['id'], report['capture']['id'])
        self.assertEqual(self.prof.report['timings']['tick']['count'], 1)

    def test_telemetry_failure_detaches_without_masking_core(self):
        original_tick = self.core.tick
        self.prof.start(60)
        self.prof.stats = None                    # simulate broken bookkeeping
        self.assertEqual(self.core.tick('pc'), 'ticked')
        self.assertEqual(self.prof.state, 'stopped')
        self.assertEqual(self.prof.report['capture']['save_reason'], 'telemetry_error')
        self.assertIs(self.core.tick, original_tick)
        self.assertEqual(sum('telemetry failed' in line for line in self.logs), 1)


class GlueChecks(unittest.TestCase):
    """__init__.py against a stub mods_base: options, buttons, console lines, disable."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.console = []
        mb = types.ModuleType('mods_base')
        mb.SETTINGS_DIR = Path(self.dir.name)

        class Opt:
            def __init__(self, identifier, *args, **kw):
                self.identifier, self.args, self.kw = identifier, args, kw
                self.value = args[0] if args else None
                self.on_press = kw.get('on_press')

        mb.SpinnerOption = type('SpinnerOption', (Opt,), {})
        mb.ButtonOption = type('ButtonOption', (Opt,), {})
        mb.build_mod = lambda **kw: types.SimpleNamespace(**kw)
        viewport = types.SimpleNamespace(ViewportConsole=types.SimpleNamespace(OutputText=self.console.append))
        self.pc = types.SimpleNamespace(Player=types.SimpleNamespace(ViewportClient=viewport))
        mb.get_pc = lambda: self.pc
        self.saved = {k: sys.modules.get(k) for k in ('mods_base', 'classic_minimap_profiler',
                                                      'classic_minimap_profiler.profiler', 'classic_minimap')}
        sys.modules['mods_base'] = mb
        for k in ('classic_minimap_profiler', 'classic_minimap_profiler.profiler'):
            sys.modules.pop(k, None)
        sys.path.insert(0, str(ROOT / 'sdk_mods'))
        import classic_minimap_profiler as glue
        self.glue = glue
        glue.PROFILER.log = lambda line: None
        self.clock = Clock()
        self.core = fake_core(self.clock)
        sys.modules['classic_minimap'] = self.core

    def tearDown(self):
        sys.path.remove(str(ROOT / 'sdk_mods'))
        for k, v in self.saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        self.dir.cleanup()

    def test_menu_and_report_location(self):
        g = self.glue
        self.assertEqual([o.identifier for o in g.mod.options],
                         ['Capture length', 'Start performance capture', 'Dump performance report',
                          'Reset performance statistics'])
        self.assertEqual(g.opt_length.value, '60 s')
        self.assertEqual(g.opt_length.args[1], ['30 s', '60 s', '120 s', '300 s'])
        self.assertEqual(g.REPORT_DIR, Path(self.dir.name) / 'classic_minimap_profiler' / 'reports')
        self.assertEqual(g.__version__, sys.modules['classic_minimap_profiler.profiler'].PROFILER_VERSION)

    def test_buttons_drive_a_capture(self):
        g = self.glue
        g.opt_length.value = '120 s'
        g.opt_start.on_press(g.opt_start)
        self.assertEqual(g.PROFILER.state, 'collecting')
        self.assertEqual(g.PROFILER.requested, 120)
        g.opt_start.on_press(g.opt_start)
        self.core.tick('pc')
        g.opt_dump.on_press(g.opt_dump)
        self.assertEqual(g.PROFILER.state, 'stopped')
        self.assertTrue((g.REPORT_DIR / 'BL1-classic-minimap-performance-report.json').exists())
        g.opt_reset.on_press(g.opt_reset)
        self.assertEqual(g.PROFILER.state, 'idle')
        g.opt_dump.on_press(g.opt_dump)
        self.assertEqual(self.console, [
            '[Classic Minimap Profiler] capture started',
            '[Classic Minimap Profiler] a capture is already running',
            '[Classic Minimap Profiler] report written to the SDK log and the reports folder',
            '[Classic Minimap Profiler] statistics reset',
            '[Classic Minimap Profiler] no capture to report yet'])

    def test_refusals_are_explained(self):
        g = self.glue
        self.core.mod.is_enabled = False
        g.on_start()
        self.assertEqual(self.console, ['[Classic Minimap Profiler] enable Classic Minimap first'])

    def test_disable_stops_a_running_capture(self):
        g = self.glue
        original = self.core.tick
        g.on_start()
        g.on_disable()
        self.assertEqual(g.PROFILER.state, 'stopped')
        self.assertIs(self.core.tick, original)
        g.on_disable()                          # idle: nothing to do
        self.assertEqual(g.PROFILER.state, 'stopped')

    def test_console_failure_is_silent(self):
        self.pc.Player = None
        self.glue.console('anything')            # no exception


class IsolationChecks(unittest.TestCase):
    def test_core_source_has_no_telemetry(self):
        text = (CORE_DIR / '__init__.py').read_text(encoding='utf-8').lower()
        for word in ('profiler', 'perf_counter', 'telemetry'):
            self.assertNotIn(word, text)

    def test_distributions_share_identical_core_bytes(self):
        from build_sdkmod import main as package
        with tempfile.TemporaryDirectory() as directory:
            standard, profiling = Path(directory) / 'standard', Path(directory) / 'profiling'
            with contextlib.redirect_stdout(io.StringIO()):
                package(str(CORE_DIR), str(standard))
                package(str(CORE_DIR), str(profiling))
                package(str(PROFILER_DIR), str(profiling))
            core_a = (standard / 'classic_minimap.sdkmod').read_bytes()
            core_b = (profiling / 'classic_minimap.sdkmod').read_bytes()
            self.assertEqual(core_a, core_b)
            self.assertEqual(sorted(p.name for p in standard.iterdir()), ['classic_minimap.sdkmod'])
            with zipfile.ZipFile(profiling / 'classic_minimap_profiler.sdkmod') as archive:
                names = archive.namelist()
                self.assertTrue(names and all(n.startswith('classic_minimap_profiler/') for n in names))
            with zipfile.ZipFile(standard / 'classic_minimap.sdkmod') as archive:
                self.assertFalse(any('profiler' in n for n in archive.namelist()))

    def test_current_core_version_is_supported(self):
        """A core version bump must be matched in the profiler's exact allowlist (decision 14), or the
        profiler refuses the shipped core."""
        import re
        source = (CORE_DIR / '__init__.py').read_text(encoding='utf-8')
        version = re.search(r'^__version__ = "([^"]+)"', source, re.M).group(1)
        self.assertIn(version, P.SUPPORTED_CORE_VERSIONS)

    def test_profiler_version_fields_match(self):
        import tomllib
        version = tomllib.loads((PROFILER_DIR / 'pyproject.toml').read_text())['project']['version']
        self.assertEqual(version, P.PROFILER_VERSION)


class FixtureChecks(unittest.TestCase):
    """The report contract fixtures stay in sync with the real producer (PERF_REPORT_V1.md)."""

    FIXTURES = HERE / 'fixtures' / 'perf_reports'

    def test_regenerated_fixtures_match_committed_bytes(self):
        import make_perf_fixtures
        saved = sys.modules.get('classic_minimap')
        with tempfile.TemporaryDirectory() as directory:
            names = make_perf_fixtures.build(directory)
            committed = sorted(p.name for p in self.FIXTURES.iterdir())
            self.assertEqual(names, committed)
            for name in names:
                self.assertEqual((Path(directory) / name).read_bytes(), (self.FIXTURES / name).read_bytes(), name)
        if saved is not None:
            sys.modules['classic_minimap'] = saved

    def test_a_capture_that_never_ends_fails_the_fixture_run_instead_of_hanging_it(self):
        """valid_reports() drives a 120 s capture in 50 ms ticks until the profiler stops itself. If stop() stops
        doing its job the loop must fail, not spin: mutants of `state != "collecting"` made the whole run wait for
        the 20 s mutation timeout (PHASE3 3cg)."""
        import make_perf_fixtures
        saved = sys.modules.get('classic_minimap')
        original = make_perf_fixtures.P.Profiler.stop
        try:
            make_perf_fixtures.P.Profiler.stop = lambda self, reason: None
            with self.assertRaisesRegex(RuntimeError, 'did not finish'):
                make_perf_fixtures.valid_reports()
        finally:
            make_perf_fixtures.P.Profiler.stop = original
            if saved is not None:
                sys.modules['classic_minimap'] = saved
            else:
                sys.modules.pop('classic_minimap', None)

    def test_fixture_set_covers_the_handoff(self):
        names = {p.stem for p in self.FIXTURES.iterdir()}
        self.assertEqual({n for n in names if n.startswith('valid-')},
                         {'valid-completed', 'valid-empty-metrics', 'valid-aborted-detach-conflict',
                          'valid-overflow', 'valid-120s'})
        self.assertEqual(len([n for n in names if n.startswith('invalid-')]), 16)

    def test_valid_fixtures_describe_their_case(self):
        load = lambda n: json.loads((self.FIXTURES / f'{n}.json').read_text(encoding='utf-8'))  # noqa: E731
        completed = load('valid-completed')
        self.assertEqual((completed['capture']['save_reason'], completed['capture']['complete']), ('completed', True))
        self.assertGreater(completed['counters']['ticks_total'], completed['counters']['ticks_admitted'])
        empty = load('valid-empty-metrics')
        self.assertTrue(all(t['count'] == 0 and t['max_ms'] is None for t in empty['timings'].values()))
        conflict = load('valid-aborted-detach-conflict')
        self.assertEqual(conflict['capture']['state'], 'aborted')
        self.assertIn('detach_conflict', conflict['limitations'])
        overflow = load('valid-overflow')
        self.assertEqual(overflow['timings']['tick']['buckets'][15], 2)
        self.assertIsNone(overflow['timings']['tick']['p99_le_ms'])
        self.assertEqual(load('valid-120s')['capture']['requested_seconds'], 120)
        for name in ('valid-completed', 'valid-120s'):
            self.assertLessEqual(len((self.FIXTURES / f'{name}.json').read_bytes()), P.REPORT_LIMIT)

    def test_serialize_is_the_published_format(self):
        report = {'b': 1, 'a': [1.5, None]}
        self.assertEqual(P.serialize(report), '{\n "b": 1,\n "a": [\n  1.5,\n  null\n ]\n}')
        with self.assertRaises(ValueError):
            P.serialize({'x': float('nan')})


class IntegrationChecks(unittest.TestCase):
    def test_real_core_scenario_with_capture_attached(self):
        import test_minimap_mod
        from ci_fixture import build_fixture
        seen = {}

        def attach(core):
            core.mod.is_enabled = True
            seen['originals'] = {name: getattr(core, name) for name in P.WRAPPED}
            seen['prof'] = P.Profiler(out_dir=Path(directory) / 'reports', log=lambda line: None)
            self.assertEqual(seen['prof'].start(300), 'collecting')

        with tempfile.TemporaryDirectory() as directory:
            movie = Path(directory) / 'synthetic.gfx'
            movie.write_bytes(build_fixture())
            with contextlib.redirect_stdout(io.StringIO()):
                test_minimap_mod.main(str(movie), on_import=attach)
            prof, core = seen['prof'], sys.modules['classic_minimap']
            # The stub build_mod does not copy on_disable onto the mod object (the real one does), and the
            # scenario calls the module function directly, so stop explicitly.
            self.assertEqual(prof.state, 'collecting')
            report = prof.stop('stopped_by_user')
            self.assertEqual(report['capture']['state'], 'stopped')
            t = report['timings']
            for name in ('tick', 'tick_admitted', 'start', 'collect', 'capture', 'rebuild_in_place',
                         'objective_key', 'threat_string', 'hidden_reason', 'cmd.tick', 'cmd.add', 'cmd.clear'):
                self.assertGreater(t[name]['count'], 0, name)
            # The scenario steps 0.06 s (over the 0.05 s throttle), so every tick is admitted here; throttled
            # ticks are covered by the unit case.
            self.assertEqual(report['counters']['ticks_admitted'], report['counters']['ticks_total'])
            self.assertGreater(report['counters']['ticks_total'], 0)
            for name in P.WRAPPED:
                self.assertIs(getattr(core, name), seen['originals'][name], name)


if __name__ == '__main__':
    unittest.main()
