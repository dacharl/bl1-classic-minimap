"""CLI scenarios for maintenance tools, using disposable files only."""
import json
import contextlib
import io
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))


def stock_package(movie):
    """Independently authored v584 package: group, movie property and inline texture bulk data."""
    names = b''.join(struct.pack('<i', len(n) + 1) + n + b'\0' + b'\0' * 8
                     for n in (b'None', b'RawData', b'ArrayProperty', b'FlashMovie', b'HUD', b'Texture'))
    export_offset = 128 + len(names)
    data_offset = export_offset + 3 * 68
    raw = (b'\0' * 4 + struct.pack('<6i', 1, 0, 2, 0, 4 + len(movie), 0)
           + struct.pack('<i', len(movie)) + movie + b'\0' * 8)
    bodies = [b'\0' * 4, raw, struct.pack('<4i', 0, 4, 4, data_offset + 4 + len(raw) + 16) + b'art!']
    exports = bytearray()
    cursor = data_offset
    for outer, name, body in zip((0, 1, 0), (3, 4, 5), bodies):
        exports += struct.pack('<6iQ4i', 0, 0, outer, name, 0, 0, 0, len(body), cursor, 0, 0) + b'\0' * 20
        cursor += len(body)
    header = bytearray(128)
    struct.pack_into('<IHH', header, 0, 0x9E2A83C1, 584, 0)
    struct.pack_into('<i', header, 12, 1)
    struct.pack_into('<6i', header, 21, 6, 128, 3, export_offset, 0, export_offset)
    header[53:69] = b'original-guid-01'
    return bytes(header + names + exports + b''.join(bodies))


class WorkflowChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def cli(self, name, *args, cwd=None):
        return subprocess.run([sys.executable, '-B', '-I', str(ROOT / 'tools' / name), *map(str, args)],
                              cwd=cwd or self.root, capture_output=True, text=True, encoding='utf-8')

    def repo(self):
        repo = self.root / 'repo'
        for folder in ('tools', 'sdk_mods', 'docs'):
            shutil.copytree(ROOT / folder, repo / folder, ignore=shutil.ignore_patterns('__pycache__', 'pk'))
        return repo

    def bundle(self, profiler=True):
        from ci_fixture import fixture_inputs
        inputs = self.root / 'inputs'
        inputs.mkdir()
        hud, status, enhanced = fixture_inputs()
        for name, data in zip(('HUD_classic.gfx', 'status_menu.gfx', 'HUD_enhanced.gfx'), (hud, status, enhanced)):
            (inputs / name).write_bytes(data)
        stock = self.root / 'stock.upk'
        stock.write_bytes(stock_package(hud))
        output = self.root / 'release'
        args = ['--inputs', inputs, '--stock-package', stock, '--output', output]
        result = self.cli('release.py', *args, *(['--profiler'] if profiler else []))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return output, stock

    def fake_game(self, stock):
        game = self.root / 'Borderlands'
        interface = game / 'WillowGame/CookedPC/Packages/Interface'
        interface.mkdir(parents=True)
        shutil.copy2(stock, interface / 'GfxHUD.upk')
        (interface / 'GfxHUD_Minimap.upk').write_bytes(b'old-package')
        mods = game / 'sdk_mods'
        mods.mkdir()
        with zipfile.ZipFile(mods / 'classic_minimap.sdkmod', 'w') as archive:
            archive.writestr('classic_minimap/pyproject.toml', '[project]\nversion = "0.9.0"\n')
        (mods / 'classic_minimap_profiler.sdkmod').write_bytes(b'keep-profiler')
        return game, interface, mods

    def test_bump_synchronizes_versions_allowlist_fixtures_and_contract(self):
        repo = self.repo()
        result = self.cli('bump_version.py', '0.10.3', '--profiler-version', '0.1.3', '--repo', repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('__version__ = "0.10.3"', (repo / 'sdk_mods/classic_minimap/__init__.py').read_text())
        self.assertIn('version = "0.10.3"', (repo / 'sdk_mods/classic_minimap/pyproject.toml').read_text())
        profiler = (repo / 'sdk_mods/classic_minimap_profiler/profiler.py').read_text()
        self.assertIn('PROFILER_VERSION = "0.1.3"', profiler)
        self.assertIn('"0.10.3"', profiler)
        self.assertIn('version = "0.1.3"', (repo / 'sdk_mods/classic_minimap_profiler/pyproject.toml').read_text())
        fixtures = repo / 'tools/fixtures/perf_reports'
        self.assertEqual(len(list(fixtures.glob('*.json'))), 21)
        report = json.loads((fixtures / 'valid-completed.json').read_bytes())
        self.assertEqual(report['producer'], {'name': 'classic_minimap_profiler', 'version': '0.1.3',
                                              'core_version': '0.10.3'})
        invalid = json.loads((fixtures / 'invalid-unlisted-version.json').read_bytes())
        self.assertEqual(invalid['producer']['version'], '9.9.9')
        for doc in ('docs/research/PERF_REPORT_V1.md', 'docs/plans/PLAN_V11_MCP_HANDOFF.md'):
            self.assertIn('0.1.3', (repo / doc).read_text(encoding='utf-8'))
        self.assertFalse((repo / 'sdk_mods/classic_minimap/__init__.py').read_bytes().startswith(b'\xef\xbb\xbf'))

    def test_bump_keeps_previous_profiler_versions_documented_and_is_repeatable(self):
        repo = self.repo()
        args = ['0.10.3', '--profiler-version', '0.1.3', '--repo', repo]
        result = self.cli('bump_version.py', *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        handoff = (repo / 'docs/plans/PLAN_V11_MCP_HANDOFF.md').read_text(encoding='utf-8')
        self.assertIn('allow 0.1.0, 0.1.1, 0.1.2 and 0.1.3', handoff)
        result = self.cli('bump_version.py', *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((repo / 'docs/plans/PLAN_V11_MCP_HANDOFF.md').read_text(encoding='utf-8'), handoff)

    def test_bump_preview_and_failure_leave_source_unchanged(self):
        repo = self.repo()
        source = repo / 'sdk_mods/classic_minimap/__init__.py'
        before = source.read_bytes()
        result = self.cli('bump_version.py', '0.10.3', '--profiler-version', '0.1.3', '--repo', repo, '--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(source.read_bytes(), before)
        (repo / 'tools/make_perf_fixtures.py').write_bytes(b'raise RuntimeError("broken generator")\n')
        result = self.cli('bump_version.py', '0.10.3', '--profiler-version', '0.1.3', '--repo', repo)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(source.read_bytes(), before)
        result = self.cli('bump_version.py', '../escape', '--profiler-version', '0.1.3', '--repo', repo)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(source.read_bytes(), before)

    def test_diag_reports_latest_snapshots_foreign_hud_zoom_and_settings(self):
        log = self.root / 'unrealsdk.log'
        snapshots = [dict(phase='running', **{'hud.MovieInfo': "GFxMovieInfo'GfxHUD_Minimap.FlashMovie.HUD'"}),
                     dict(phase='stockhud', **{'hud.MovieInfo': "GFxMovieInfo'GfxHUD_MOD.FlashMovie.HUD'",
                                              'template.MovieInfo': "GFxMovieInfo'GfxHUD_MOD.FlashMovie.HUD'"},
                          zoom_fit={'points': [(1, 2, 3)], 'raw': 4715.849, 'fitted': 400, 'final': 400})]
        log.write_text('2026-10-25 02:00:00Z INFO| [Classic Minimap] map ready: Arid\n'
                       + '\n'.join(f'2026-10-25 02:01:0{i}Z INFO| [Classic Minimap] diagnostics: {s!r}'
                                   for i, s in enumerate(snapshots))
                       + '\n2026-10-25 02:02:00Z WARN| [Classic Minimap] no map anchor; waiting\n',
                       encoding='utf-8')
        settings = self.root / 'settings'
        settings.mkdir()
        (settings / 'classic_minimap_anchors.jsonl').write_text(
            '{"anchor":"AridAnchor","fields":{"MapFrame":"Arid"},"markers":25}\n', encoding='utf-8')
        reports = settings / 'classic_minimap_profiler/reports'
        reports.mkdir(parents=True)
        (reports / 'BL1-classic-minimap-performance-summary.txt').write_text('admitted updates: 872', encoding='utf-8')
        result = self.cli('diag.py', log, '--last', '1', '--settings', settings, '--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(len(report['snapshots']), 1)
        self.assertEqual(report['snapshots'][0]['state']['phase'], 'stockhud')
        self.assertIn('GfxHUD_MOD', report['foreign_hud_movies'][0])
        self.assertEqual(report['snapshots'][0]['state']['zoom_fit']['raw'], 4715.849)
        self.assertEqual(report['anchors']['frames'], {'Arid': 1})
        self.assertIn('872', report['profiler_summary'])
        self.assertIn('02:00:00', report['events'][0]['timestamp'])
        self.assertEqual(len(report['warnings']), 1)

    def test_diag_survives_truncated_snapshots_and_nonfinite_gfx_reads_without_executing_code(self):
        log = self.root / 'unrealsdk.log'
        log.write_text("[Classic Minimap] diagnostics: {'phase': 'running', 'themap_w': inf}\n"
                       "[Classic Minimap] diagnostics: {'phase':\n"
                       "[Classic Minimap] diagnostics: {'phase': {'unexpected-set'}}\n"
                       "[Classic Minimap] diagnostics: __import__('pathlib').Path('executed').touch()\n",
                       encoding='utf-8')
        result = self.cli('diag.py', log, '--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['latest_state']['phase'], 'running')
        self.assertIsNone(report['latest_state']['themap_w'])
        self.assertEqual(len(report['parse_errors']), 3)
        self.assertFalse((self.root / 'executed').exists())
        result = self.cli('diag.py', log)
        self.assertIn('Phase: running', result.stdout)

    def test_release_builds_tested_bundle_with_optional_profiler_and_hash_manifest(self):
        from ci_fixture import fixture_inputs
        import hashlib
        inputs = self.root / 'inputs'
        inputs.mkdir()
        hud, status, enhanced = fixture_inputs()
        for name, data in zip(('HUD_classic.gfx', 'status_menu.gfx', 'HUD_enhanced.gfx'), (hud, status, enhanced)):
            (inputs / name).write_bytes(data)
        stock = self.root / 'stock.upk'
        stock.write_bytes(stock_package(hud))
        output = self.root / 'release'
        result = self.cli('release.py', '--inputs', inputs, '--stock-package', stock, '--output', output, '--profiler')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest = json.loads((output / 'release.json').read_bytes())
        self.assertEqual(manifest['core_version'], '0.10.2')
        self.assertEqual(manifest['profiler_version'], '0.1.2')
        for name in ('GfxHUD_Minimap.upk', 'classic_minimap.sdkmod', 'classic_minimap_profiler.sdkmod', 'HUD_minimap.gfx'):
            self.assertEqual(manifest['files'][name], hashlib.sha256((output / name).read_bytes()).hexdigest())
        self.assertEqual(manifest['stock_sha256'], hashlib.sha256(stock.read_bytes()).hexdigest())
        self.assertIn('all minimap AS checks passed', result.stdout)
        self.assertIn('all minimap mod integration checks passed', result.stdout)
        result = self.cli('release.py', '--inputs', inputs, '--stock-package', stock, '--output', output)
        self.assertNotEqual(result.returncode, 0, 'an existing release must never be overwritten')

    def test_release_preview_and_failed_build_do_not_publish_partial_outputs(self):
        from ci_fixture import fixture_inputs
        inputs = self.root / 'inputs'
        inputs.mkdir()
        hud, status, enhanced = fixture_inputs()
        for name, data in zip(('HUD_classic.gfx', 'status_menu.gfx', 'HUD_enhanced.gfx'), (hud, status, enhanced)):
            (inputs / name).write_bytes(data)
        stock = self.root / 'stock.upk'
        stock.write_bytes(stock_package(hud))
        output = self.root / 'release'
        args = ['--inputs', inputs, '--stock-package', stock, '--output', output]
        result = self.cli('release.py', *args, '--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(output.exists())
        (inputs / 'HUD_enhanced.gfx').write_bytes(b'not a movie')
        result = self.cli('release.py', *args)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())
        self.assertFalse(list(self.root.glob('.release-*')))

    def test_release_can_bump_both_versions_before_building(self):
        from ci_fixture import fixture_inputs
        repo = self.repo()
        inputs = self.root / 'inputs'
        inputs.mkdir()
        hud, status, enhanced = fixture_inputs()
        for name, data in zip(('HUD_classic.gfx', 'status_menu.gfx', 'HUD_enhanced.gfx'), (hud, status, enhanced)):
            (inputs / name).write_bytes(data)
        stock = self.root / 'stock.upk'
        stock.write_bytes(stock_package(hud))
        output = self.root / 'release'
        result = subprocess.run([sys.executable, '-B', '-I', str(repo / 'tools/release.py'),
                                 '--inputs', str(inputs), '--stock-package', str(stock), '--output', str(output),
                                 '--version', '0.10.3', '--profiler-version', '0.1.3', '--profiler'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest = json.loads((output / 'release.json').read_bytes())
        self.assertEqual((manifest['core_version'], manifest['profiler_version']), ('0.10.3', '0.1.3'))

    def test_install_backs_up_replaced_version_verifies_copies_and_keeps_profiler_opt_in(self):
        output, stock = self.bundle()
        game, interface, mods = self.fake_game(stock)
        backups = self.root / 'backups'
        result = self.cli('install.py', output, '--game', game, '--stock-package', stock, '--backups', backups)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((interface / 'GfxHUD.upk').read_bytes(), stock.read_bytes())
        self.assertEqual((interface / 'GfxHUD_Minimap.upk').read_bytes(), (output / 'GfxHUD_Minimap.upk').read_bytes())
        self.assertEqual((mods / 'classic_minimap.sdkmod').read_bytes(), (output / 'classic_minimap.sdkmod').read_bytes())
        self.assertEqual((mods / 'classic_minimap_profiler.sdkmod').read_bytes(), b'keep-profiler')
        folders = list(backups.glob('v0.9.0-*'))
        self.assertEqual(len(folders), 1)
        self.assertEqual((folders[0] / 'GfxHUD_Minimap.upk').read_bytes(), b'old-package')
        self.assertTrue((folders[0] / 'install.json').exists())
        self.assertIn('| `sdk_mods/classic_minimap.sdkmod` |', result.stdout)
        self.assertIn('SHA-256', result.stdout)
        result = self.cli('install.py', output, '--game', game, '--stock-package', stock,
                          '--backups', backups, '--profiler')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((mods / 'classic_minimap_profiler.sdkmod').read_bytes(),
                         (output / 'classic_minimap_profiler.sdkmod').read_bytes())

    def test_install_dry_run_and_tampered_bundle_never_change_game_files(self):
        output, stock = self.bundle(profiler=False)
        game, interface, mods = self.fake_game(stock)
        backups = self.root / 'backups'
        args = [output, '--game', game, '--stock-package', stock, '--backups', backups]
        result = self.cli('install.py', *args, '--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(backups.exists())
        self.assertEqual((interface / 'GfxHUD_Minimap.upk').read_bytes(), b'old-package')
        result = self.cli('install.py', *args, '--profiler')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('does not include the profiler', result.stderr)
        package = output / 'GfxHUD_Minimap.upk'
        data = package.read_bytes()
        package.write_bytes(data[:-1] + b'?')  # damage the texture payload, not the movie
        result = self.cli('install.py', *args)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHA-256 mismatch', result.stderr)
        # Even a refreshed manifest cannot hide broken bulk-data/export preservation.
        import hashlib
        manifest = json.loads((output / 'release.json').read_bytes())
        manifest['files'][package.name] = hashlib.sha256(package.read_bytes()).hexdigest()
        (output / 'release.json').write_text(json.dumps(manifest), encoding='utf-8')
        result = self.cli('install.py', *args)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('bulk-data relocation', result.stderr)
        self.assertFalse(backups.exists())
        self.assertEqual((interface / 'GfxHUD_Minimap.upk').read_bytes(), b'old-package')
        self.assertEqual((mods / 'classic_minimap_profiler.sdkmod').read_bytes(), b'keep-profiler')

    def test_install_refuses_running_game_and_rolls_back_on_copy_failure(self):
        # Inject only OS process enumeration and file replacement failures at the CLI boundary.
        import install
        output, stock = self.bundle()
        game, interface, mods = self.fake_game(stock)
        backups = self.root / 'backups'
        args = list(map(str, [output, '--game', game, '--stock-package', stock, '--backups', backups]))
        old_core = (mods / 'classic_minimap.sdkmod').read_bytes()
        running = '"Borderlands.exe","1234","Console","1","123 K"\n' if sys.platform == 'win32' else 'Borderlands.exe\n'
        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0, running, '')):
            with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
                install.main(args)
            self.assertIn('is running', err.getvalue())
        self.assertFalse(backups.exists())
        replace = os.replace

        def fail_core(source, target):
            if Path(target).name == 'classic_minimap.sdkmod':
                raise OSError('simulated disk error')
            return replace(source, target)

        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0, '', '')):
            with patch('os.replace', side_effect=fail_core):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    install.main(args)
        self.assertEqual((interface / 'GfxHUD_Minimap.upk').read_bytes(), b'old-package')
        self.assertEqual((mods / 'classic_minimap.sdkmod').read_bytes(), old_core)
        self.assertEqual((interface / 'GfxHUD.upk').read_bytes(), stock.read_bytes())
        record = json.loads(next(backups.glob('*/install.json')).read_bytes())
        self.assertEqual(record['status'], 'rolled_back')
        self.assertFalse(list(game.rglob('.minimap-*')))


if __name__ == '__main__':
    unittest.main()
