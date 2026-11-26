"""CLI scenarios for maintenance tools, using disposable files only."""
import json
import contextlib
import io
import os
import re
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
from swfbuild import core_version  # noqa: E402


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

    def install(self, *args, running=''):
        """install.py's CLI, run in this process with the OS process query injected (`running` is the
        listing it returns), so the result never depends on whether the real game is open (PHASE3 3bx)."""
        import install
        out, err, code = io.StringIO(), io.StringIO(), 0
        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0, running, '')):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    install.main(list(map(str, args)))
                except SystemExit as stop:
                    code = stop.code or 0
        return subprocess.CompletedProcess(args, code, out.getvalue(), err.getvalue())

    def repo(self):
        repo = self.root / 'repo'
        for folder in ('tools', 'sdk_mods', 'docs'):
            shutil.copytree(ROOT / folder, repo / folder, ignore=shutil.ignore_patterns('__pycache__', 'pk'))
        return repo

    def inputs(self):
        from ci_fixture import fixture_inputs
        inputs = self.root / 'inputs'
        inputs.mkdir()
        hud, status, enhanced = fixture_inputs()
        for name, data in zip(('HUD_classic.gfx', 'status_menu.gfx', 'HUD_enhanced.gfx'), (hud, status, enhanced)):
            (inputs / name).write_bytes(data)
        return inputs

    def bundle(self, profiler=True):
        output = self.root / 'release'
        result = self.cli('release.py', '--inputs', self.inputs(), '--output', output,
                          *(['--profiler'] if profiler else []))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return output

    def fake_game(self):
        from ci_fixture import fixture_inputs
        from test_hudmovie import package
        hud, status, _ = fixture_inputs()
        game = self.root / 'Borderlands'
        interface = game / 'WillowGame/CookedPC/Packages/Interface'
        interface.mkdir(parents=True)
        (interface / 'GfxHUD.upk').write_bytes(stock_package(hud))
        (interface / 'menus_ingame_redux.upk').write_bytes(package('FlashMovies.status_menu', status))
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
        source = (repo / 'sdk_mods/classic_minimap_profiler/profiler.py').read_text(encoding='utf-8')
        current = re.search(r'PROFILER_VERSION = "([^"]+)"', source)[1]
        args = ['0.99.0', '--profiler-version', '0.9.0', '--repo', repo]
        result = self.cli('bump_version.py', *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        handoff = (repo / 'docs/plans/PLAN_V11_MCP_HANDOFF.md').read_text(encoding='utf-8')
        self.assertRegex(handoff, r'allow 0\.1\.0, [0-9., ]*%s and 0\.9\.0' % re.escape(current))
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
        """PLAN_V13: the bundle is the .sdkmod files only (no movie, no package: players build their own); both
        art variants are built and pass both suites, and their hashes are recorded."""
        from ci_fixture import fixture_inputs
        from swfbuild import build
        import hashlib
        inputs = self.inputs()
        output = self.root / 'release'
        result = self.cli('release.py', '--inputs', inputs, '--output', output, '--profiler')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest = json.loads((output / 'release.json').read_bytes())
        profiler_source = (ROOT / 'sdk_mods/classic_minimap_profiler/profiler.py').read_text(encoding='utf-8')
        self.assertEqual(manifest['core_version'], core_version())
        self.assertEqual(manifest['profiler_version'], re.search(r'PROFILER_VERSION = "([^"]+)"', profiler_source)[1])
        self.assertEqual(sorted(p.name for p in output.iterdir()),
                         ['classic_minimap.sdkmod', 'classic_minimap_profiler.sdkmod', 'release.json'])
        for name in ('classic_minimap.sdkmod', 'classic_minimap_profiler.sdkmod'):
            self.assertEqual(manifest['files'][name], hashlib.sha256((output / name).read_bytes()).hexdigest())
        hud, status, enhanced = fixture_inputs()
        for art, enh in (('enhanced', enhanced), ('original', None)):
            expected = build(hud, status, enh, manifest['core_version'])[0]
            self.assertEqual(manifest['movies'][art], hashlib.sha256(expected).hexdigest(), art)
        self.assertEqual(result.stdout.count('all minimap AS checks passed'), 2)
        self.assertEqual(result.stdout.count('all minimap mod integration checks passed'), 2)
        result = self.cli('release.py', '--inputs', inputs, '--output', output)
        self.assertNotEqual(result.returncode, 0, 'an existing release must never be overwritten')

    def test_release_checks_the_in_mod_build_against_a_game_folder(self):
        """--game runs the mod's own build (hudmovie) on the game folder's packages; it must give the movie the
        release tested, byte for byte (decision 11's determinism)."""
        inputs = self.inputs()
        game, interface, _ = self.fake_game()
        result = self.cli('release.py', '--inputs', inputs, '--game', game, '--output', self.root / 'ok')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('in-mod build matches (original art)', result.stdout)
        from ci_fixture import movie
        from test_hudmovie import package
        (interface / 'menus_ingame_redux.upk').write_bytes(package('FlashMovies.status_menu', movie([])))
        result = self.cli('release.py', '--inputs', inputs, '--game', game, '--output', self.root / 'bad')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'bad').exists())

    def test_release_preview_and_failed_build_do_not_publish_partial_outputs(self):
        inputs = self.inputs()
        output = self.root / 'release'
        args = ['--inputs', inputs, '--output', output]
        result = self.cli('release.py', *args, '--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(output.exists())
        (inputs / 'HUD_enhanced.gfx').write_bytes(b'not a movie')
        result = self.cli('release.py', *args)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())
        self.assertFalse(list(self.root.glob('.release-*')))

    def test_release_can_bump_both_versions_before_building(self):
        repo = self.repo()
        inputs = self.inputs()
        output = self.root / 'release'
        result = subprocess.run([sys.executable, '-B', '-I', str(repo / 'tools/release.py'),
                                 '--inputs', str(inputs), '--output', str(output),
                                 '--version', '0.10.3', '--profiler-version', '0.1.3', '--profiler'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest = json.loads((output / 'release.json').read_bytes())
        self.assertEqual((manifest['core_version'], manifest['profiler_version']), ('0.10.3', '0.1.3'))

    def test_install_backs_up_replaced_version_verifies_copies_and_keeps_profiler_opt_in(self):
        """PLAN_V13: only the .sdkmod files are installed; an old GfxHUD_Minimap.upk is left alone and pointed
        out (decision 7), and no game file is touched."""
        output = self.bundle()
        game, interface, mods = self.fake_game()
        stock = (interface / 'GfxHUD.upk').read_bytes()
        backups = self.root / 'backups'
        result = self.install(output, '--game', game, '--backups', backups)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((interface / 'GfxHUD.upk').read_bytes(), stock)
        self.assertEqual((interface / 'GfxHUD_Minimap.upk').read_bytes(), b'old-package')
        self.assertIn('GfxHUD_Minimap.upk is no longer used', result.stdout)
        self.assertEqual((mods / 'classic_minimap.sdkmod').read_bytes(), (output / 'classic_minimap.sdkmod').read_bytes())
        self.assertEqual((mods / 'classic_minimap_profiler.sdkmod').read_bytes(), b'keep-profiler')
        folders = list(backups.glob('v0.9.0-*'))
        self.assertEqual(len(folders), 1)
        self.assertEqual(sorted(p.name for p in folders[0].iterdir()), ['classic_minimap.sdkmod', 'install.json'])
        self.assertIn('| `sdk_mods/classic_minimap.sdkmod` |', result.stdout)
        self.assertIn('SHA-256', result.stdout)
        result = self.install(output, '--game', game, '--backups', backups, '--profiler')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((mods / 'classic_minimap_profiler.sdkmod').read_bytes(),
                         (output / 'classic_minimap_profiler.sdkmod').read_bytes())

    def test_install_dry_run_and_tampered_bundle_never_change_game_files(self):
        output = self.bundle(profiler=False)
        game, interface, mods = self.fake_game()
        backups = self.root / 'backups'
        args = [output, '--game', game, '--backups', backups]
        old_core = (mods / 'classic_minimap.sdkmod').read_bytes()
        result = self.install(*args, '--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(backups.exists())
        result = self.install(*args, '--profiler')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('does not include the profiler', result.stderr)
        core = output / 'classic_minimap.sdkmod'
        core.write_bytes(core.read_bytes() + b'?')
        result = self.install(*args)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHA-256 mismatch', result.stderr)
        self.assertFalse(backups.exists())
        self.assertEqual((mods / 'classic_minimap.sdkmod').read_bytes(), old_core)
        self.assertEqual((mods / 'classic_minimap_profiler.sdkmod').read_bytes(), b'keep-profiler')
        (output / 'release.json').write_text(json.dumps({'schema_version': 1, 'files': {
            'classic_minimap.sdkmod': 'x', 'GfxHUD_Minimap.upk': 'y'}}), encoding='utf-8')
        result = self.install(*args)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('missing or unexpected files', result.stderr)

    def test_install_refuses_running_game_and_rolls_back_on_copy_failure(self):
        # Inject only OS process enumeration and file replacement failures at the CLI boundary.
        output = self.bundle()
        game, interface, mods = self.fake_game()
        stock = (interface / 'GfxHUD.upk').read_bytes()
        backups = self.root / 'backups'
        args = [output, '--game', game, '--backups', backups, '--profiler']
        old_core = (mods / 'classic_minimap.sdkmod').read_bytes()
        running = '"Borderlands.exe","1234","Console","1","123 K"\n' if sys.platform == 'win32' else 'Borderlands.exe\n'
        result = self.install(*args, running=running)
        self.assertEqual(result.returncode, 1)
        self.assertIn('is running', result.stderr)
        self.assertFalse(backups.exists())
        replace = os.replace

        def fail_core(source, target):
            if Path(target).name == 'classic_minimap.sdkmod':
                raise OSError('simulated disk error')
            return replace(source, target)

        with patch('os.replace', side_effect=fail_core):
            result = self.install(*args)
        self.assertEqual(result.returncode, 1)
        self.assertIn('simulated disk error', result.stderr)
        self.assertEqual((interface / 'GfxHUD_Minimap.upk').read_bytes(), b'old-package')
        self.assertEqual((mods / 'classic_minimap.sdkmod').read_bytes(), old_core)
        self.assertEqual((mods / 'classic_minimap_profiler.sdkmod').read_bytes(), b'keep-profiler')
        self.assertEqual((interface / 'GfxHUD.upk').read_bytes(), stock)
        record = json.loads(next(backups.glob('*/install.json')).read_bytes())
        self.assertEqual(record['status'], 'rolled_back')
        self.assertFalse(list(game.rglob('.minimap-*')))

    def test_release_notes_come_from_the_versioned_file_then_the_input_and_otherwise_fail(self):
        import release_notes
        notes = self.root / 'release_notes'
        notes.mkdir()
        (notes / '1.0.0.md').write_text('\n# From the file\n\nFirst release.\n\n', encoding='utf-8')
        self.assertEqual(release_notes.resolve_notes('1.0.0', notes, 'typed in the UI'),
                         '# From the file\n\nFirst release.\n', 'the file wins over the input')
        self.assertEqual(release_notes.resolve_notes('1.0.1', notes, ' Fixed the zoom. \n'), 'Fixed the zoom.\n')
        for missing in ('', '  \n', None):
            with self.assertRaises(release_notes.ReleaseNotesError) as stop:
                release_notes.resolve_notes('1.0.1', notes, missing)
            self.assertIn('docs/release_notes/1.0.1.md', str(stop.exception))
            self.assertIn("'notes' input", str(stop.exception))
        (notes / '1.0.2.md').write_text(' \n', encoding='utf-8')
        with self.assertRaises(release_notes.ReleaseNotesError):
            release_notes.resolve_notes('1.0.2', notes, None)

    def test_release_notes_report_errors_and_exit_codes_in_process(self):
        import release_notes
        elsewhere = self.root / 'not-a-repository'
        elsewhere.mkdir()
        with contextlib.chdir(elsewhere):
            with self.assertRaises(release_notes.ReleaseNotesError) as stop:
                release_notes.git('log', '--format=%h')
            self.assertIn('git log --format=%h failed', str(stop.exception))
            for argv, code, where in ((['--version', '1.0.1', '--out-dir', 'dist'], 1, 'err'),
                                      (['--version', '1.0.1', '--notes', 'Typed.', '--out-dir', 'dist'], 1, 'err')):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    self.assertEqual(release_notes.run(argv), code)
                self.assertTrue(err.getvalue().strip(), 'the error goes to stderr, not a traceback')
                self.assertEqual(out.getvalue(), '')
        out = io.StringIO()
        with contextlib.chdir(self.root), contextlib.redirect_stdout(out):
            self.assertEqual(release_notes.run(['--version', '1.0.1', '--notes', 'Typed.', '--out-dir', 'dist']), 1)
        self.assertFalse((self.root / 'dist' / 'release-notes.md').exists(), 'nothing is written on failure')

    def test_release_changes_list_commits_since_the_previous_tag_by_type(self):
        import release_notes
        tags = ['v0.9.0', 'v1.0.0', 'v0.10.2', 'v0.10.10', 'nightly', 'v2.0.0', 'v1.0']
        self.assertEqual(release_notes.previous_tag(tags, '1.0.0'), 'v0.10.10')
        self.assertEqual(release_notes.previous_tag(tags, '0.9.0'), None)
        self.assertEqual(release_notes.previous_tag([], '1.0.0'), None)
        log = ['aaa1111\tfeat(mod): add the minimap', 'bbb2222\tfix: stop a crash', 'ccc3333\tfeat!: new options',
               'ddd4444\tdocs: explain it', 'eee5555\tUpdate things', 'fff6666\tperf(mod): speed up the merge']
        text = release_notes.changes_text('1.0.0', 'v0.10.10', log)
        self.assertTrue(text.startswith('# Changes in v1.0.0\n\nSince v0.10.10: 6 commits.\n'), text)
        order = [text.index(h) for h in ('## Features', '## Fixes', '## Performance', '## Documentation', '## Other')]
        self.assertEqual(order, sorted(order))
        self.assertIn('- add the minimap (`aaa1111`)', text)
        self.assertIn('- **breaking:** new options (`ccc3333`)', text)
        self.assertIn('- Update things (`eee5555`)', text)
        self.assertNotIn('## Tests', text)
        self.assertIn('Since the first commit: 1 commit.', release_notes.changes_text('1.0.0', None, log[:1]))

    def test_release_notes_cli_writes_the_body_and_the_supplement_in_a_git_checkout(self):
        env = dict(os.environ, GIT_AUTHOR_NAME='T', GIT_AUTHOR_EMAIL='t@example.invalid',
                   GIT_COMMITTER_NAME='T', GIT_COMMITTER_EMAIL='t@example.invalid')

        def git(*args):
            subprocess.run(['git', *args], cwd=self.root, env=env, check=True, capture_output=True)
        git('init', '-q')
        for subject in ('feat: before the tag', 'fix: also before'):
            git('commit', '-q', '--allow-empty', '-m', subject)
        git('tag', 'v0.9.0')
        git('commit', '-q', '--allow-empty', '-m', 'fix(mod): after the tag')
        (self.root / 'docs' / 'release_notes').mkdir(parents=True)
        (self.root / 'docs' / 'release_notes' / '1.0.0.md').write_text('The first release.\n', encoding='utf-8')
        out = self.root / 'dist'
        import release_notes
        with contextlib.chdir(self.root), contextlib.redirect_stdout(io.StringIO()) as printed:
            release_notes.main(['--version', '1.0.0', '--out-dir', str(out)])
        self.assertIn('1 commits since v0.9.0', printed.getvalue())
        body = (out / 'release-notes.md').read_text(encoding='utf-8')
        self.assertTrue(body.startswith('The first release.\n'), body)
        self.assertIn('classic_minimap.sdkmod', body)
        self.assertIn('classic_minimap-changes.md', body)
        changes = (out / 'classic_minimap-changes.md').read_text(encoding='utf-8')
        self.assertIn('after the tag', changes)
        self.assertNotIn('before the tag', changes)
        missing = self.cli('release_notes.py', '--version', '1.0.1', '--out-dir', out, cwd=self.root)
        self.assertEqual(missing.returncode, 1)
        self.assertIn('docs/release_notes/1.0.1.md', missing.stderr)
        typed = self.cli('release_notes.py', '--version', '1.0.1', '--notes', 'Typed notes.', '--out-dir', out,
                         cwd=self.root)
        self.assertEqual(typed.returncode, 0, typed.stderr)
        self.assertTrue((out / 'release-notes.md').read_text(encoding='utf-8').startswith('Typed notes.\n'))

    def test_release_workflow_checks_notes_before_ci_and_publishes_the_tag_notes_and_artifacts(self):
        text = (ROOT / '.github' / 'workflows' / 'release.yml').read_text(encoding='utf-8')
        jobs = text.split('\njobs:\n', 1)[1]
        first_job = jobs.split('\n  checks:\n', 1)[0]
        self.assertIn('\n      notes:\n', text.split('\npermissions:', 1)[0], 'a notes input')
        self.assertIn('release_notes.py', first_job, 'notes are resolved before CI starts')
        self.assertIn('Require a new release tag', first_job, 'an existing tag fails before CI starts')
        publish = text[text.index('gh release create'):]
        for needle in ('--target "$GITHUB_SHA"', '--notes-file', 'dist/classic_minimap.sdkmod',
                       'dist/classic_minimap-changes.md'):
            self.assertIn(needle, publish)


if __name__ == '__main__':
    unittest.main()
