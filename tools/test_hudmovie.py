"""The in-game build of the player-built movie (PLAN_V13): input discovery, the movie cache, fallbacks.

Packages here are synthetic: tiny UE3 packages wrapping the asset-free fixture movies, so no game files are
needed. The real-file check is local (release.py runs the build from the game folders).
"""
import hashlib
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mod_source  # noqa: E402

hudmovie = mod_source.load('hudmovie')
swfbuild = mod_source.load('swfbuild')
from ci_fixture import fixture_inputs, movie  # noqa: E402

VERSION = '9.9.9'


def fstring(s):
    b = s.encode('latin-1') + b'\0'
    return struct.pack('<i', len(b)) + b


def package(path, gfx):
    """An uncompressed v584 package with `path` (e.g. FlashMovie.HUD) as a GFxMovieInfo holding `gfx`."""
    outer_name, name = path.split('.')
    names = ['None', 'RawData', 'ArrayProperty', outer_name, name]
    idx = {n: i for i, n in enumerate(names)}
    header = struct.pack('<IHHi', 0x9E2A83C1, 584, 0, 0) + fstring('None') + struct.pack('<I', 0)
    tables_at = len(header) + 24
    name_table = b''.join(fstring(n) + b'\0' * 8 for n in names)
    exp_off = tables_at + len(name_table)
    raw = struct.pack('<i', 0) + struct.pack('<iiiiii', idx['RawData'], 0, idx['ArrayProperty'], 0, 4 + len(gfx), 0)
    raw += struct.pack('<i', len(gfx)) + gfx + struct.pack('<ii', idx['None'], 0)
    data_off = exp_off + 2 * 68

    def export(name_i, outer, size, off):
        return (struct.pack('<6i', 0, 0, outer, name_i, 0, 0) + struct.pack('<Q', 0) + struct.pack('<2i', size, off)
                + struct.pack('<Ii', 0, 0) + b'\0' * 16 + struct.pack('<I', 0))
    exports = export(idx[outer_name], 0, 0, data_off) + export(idx[name], 1, len(raw), data_off)
    counts = struct.pack('<6i', len(names), tables_at, 2, exp_off, 0, data_off)
    return header + counts + name_table + exports + raw


class Game:
    """A classic game folder (and optionally Enhanced's) holding synthetic input packages."""

    def __init__(self, root, enhanced_movie=None, enhanced_where='sibling'):
        hud, status, enhanced = fixture_inputs()
        self.root = Path(root)
        self.game = self.root / 'steamapps' / 'common' / 'Borderlands'
        self.settings = self.game / 'sdk_mods' / 'settings'
        self.settings.mkdir(parents=True)
        interface = self.game / hudmovie.INTERFACE
        interface.mkdir(parents=True)
        (interface / 'GfxHUD.upk').write_bytes(package('FlashMovie.HUD', hud))
        (interface / 'menus_ingame_redux.upk').write_bytes(package('FlashMovies.status_menu', status))
        self.movies = (hud, status, enhanced)
        self.enhanced_dir = None
        if enhanced_where:
            base = {'sibling': self.root / 'steamapps' / 'common',
                    'library': self.root / 'sdcard' / 'steamapps' / 'common'}.get(enhanced_where, self.root / 'other')
            self.enhanced_dir = base / hudmovie.ENHANCED_FOLDER
            (self.enhanced_dir / hudmovie.INTERFACE).mkdir(parents=True)
            body = package('FlashMovie.HUD', enhanced if enhanced_movie is None else enhanced_movie)
            (self.enhanced_dir / hudmovie.INTERFACE / 'GfxHUD.upk').write_bytes(body)

    def provide(self, **kw):
        kw.setdefault('vdfs', ())
        return hudmovie.provide(self.game, self.settings, VERSION, **kw)


class BuildMovieChecks(unittest.TestCase):
    def setUp(self):
        self.hud, self.status, self.enhanced = fixture_inputs()

    def test_builds_from_the_packages_with_enhanced_art(self):
        data, art, notes = hudmovie.build_movie(package('FlashMovie.HUD', self.hud),
                                                package('FlashMovies.status_menu', self.status),
                                                package('FlashMovie.HUD', self.enhanced), VERSION)
        self.assertEqual((art, notes), ('enhanced', []))
        self.assertEqual(data, swfbuild.build(self.hud, self.status, self.enhanced, VERSION)[0])

    def test_without_enhanced_builds_original_art(self):
        data, art, notes = hudmovie.build_movie(package('FlashMovie.HUD', self.hud),
                                                package('FlashMovies.status_menu', self.status), None, VERSION)
        self.assertEqual((art, notes), ('original', []))
        self.assertEqual(data, swfbuild.build(self.hud, self.status, None, VERSION)[0])

    def test_unreadable_or_incomplete_enhanced_falls_back_to_original_art(self):
        """Decision 17: an Enhanced package we can't use is reported, and the build goes on with original art."""
        lacking = movie([struct.pack('<H', 81)])     # garbage: no shapes 108, 110, 127, 179...
        for label, enh in (('garbage', b'not a package'), ('lacking', package('FlashMovie.HUD', lacking)),
                           ('compressed', package('FlashMovie.HUD', b'CWS' + self.enhanced[3:]))):
            data, art, notes = hudmovie.build_movie(package('FlashMovie.HUD', self.hud),
                                                    package('FlashMovies.status_menu', self.status), enh, VERSION)
            self.assertEqual(art, 'original', label)
            self.assertEqual(data, swfbuild.build(self.hud, self.status, None, VERSION)[0], label)
            self.assertEqual(len(notes), 1, label)
            self.assertIn("Enhanced's HUD package", notes[0], label)

    def test_unusable_classic_input_fails_the_build(self):
        for label, hud_pkg, status_pkg in (
                ('garbage hud', b'junk', package('FlashMovies.status_menu', self.status)),
                ('wrong export', package('FlashMovie.HUD', self.hud), package('FlashMovie.HUD', self.status)),
                ('no font', package('FlashMovie.HUD', movie([])), package('FlashMovies.status_menu', self.status))):
            with self.assertRaises(hudmovie.BuildFailed, msg=label):
                hudmovie.build_movie(hud_pkg, status_pkg, None, VERSION)


class ProvideChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.calls = []
        real = hudmovie.build_movie

        def counting(*args):
            self.calls.append(args)
            return real(*args)
        hudmovie.build_movie = counting
        self.addCleanup(setattr, hudmovie, 'build_movie', real)
        self.addCleanup(self.tmp.cleanup)

    def test_first_enable_builds_and_later_ones_read_the_cache(self):
        game = Game(self.root)
        first = game.provide()
        self.assertEqual((first.art, first.cached, len(self.calls)), ('enhanced', False, 1))
        self.assertEqual(first.enhanced, game.enhanced_dir)
        second = game.provide()
        self.assertEqual((second.data, second.art, second.cached, len(self.calls)), (first.data, 'enhanced', True, 1))
        self.assertTrue((game.settings / hudmovie.CACHE_NAMES[True]).is_file())

    def test_cache_is_rebuilt_when_an_input_changes_even_at_the_same_size(self):
        """Decision 6: the key is every input's SHA-256, not size or time."""
        game = Game(self.root)
        game.provide()
        upk = game.game / hudmovie.INTERFACE / 'menus_ingame_redux.upk'
        body = bytearray(upk.read_bytes())
        body[-1] ^= 0xFF                              # same size, one byte different (after the movie)
        upk.write_bytes(bytes(body))
        os.utime(upk, (0, 0))
        self.assertFalse(game.provide().cached)
        self.assertEqual(len(self.calls), 2)

    def test_cache_key_covers_version_art_choice_and_rebuild(self):
        game = Game(self.root)
        game.provide()
        self.assertFalse(hudmovie.provide(game.game, game.settings, '9.9.10', vdfs=()).cached)
        off = game.provide(use_enhanced=False)
        self.assertEqual((off.art, off.cached, off.enhanced), ('original', False, None))
        self.assertTrue(game.provide(use_enhanced=False).cached)
        self.assertFalse(game.provide(use_enhanced=False, rebuild=True).cached)
        self.assertEqual(len(self.calls), 4)

    def test_each_art_choice_keeps_its_own_cache(self):
        """Run 21: switching "Use Enhanced artwork" back and forth rebuilt every time (one cache slot)."""
        game = Game(self.root)
        self.assertEqual(game.provide().art, 'enhanced')
        self.assertEqual(game.provide(use_enhanced=False).art, 'original')
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(game.provide().cached)
        self.assertTrue(game.provide(use_enhanced=False).cached)
        self.assertEqual(len(self.calls), 2)

    def test_damaged_cache_is_rebuilt(self):
        game = Game(self.root)
        first = game.provide()
        (game.settings / hudmovie.CACHE_NAMES[True]).write_bytes(first.data[:100])
        again = game.provide()
        self.assertEqual((again.cached, again.data), (False, first.data))

    def test_missing_classic_input_fails_with_its_path(self):
        game = Game(self.root)
        (game.game / hudmovie.INTERFACE / 'menus_ingame_redux.upk').unlink()
        with self.assertRaises(hudmovie.BuildFailed) as raised:
            game.provide()
        self.assertIn('menus_ingame_redux.upk', str(raised.exception))

    def test_unwritable_cache_keeps_the_movie_in_memory(self):
        game = Game(self.root)
        (game.settings / hudmovie.CACHE_NAMES[True]).mkdir()        # a folder where the cache file goes
        result = game.provide()
        self.assertEqual((result.cached, result.art), (False, 'enhanced'))
        self.assertTrue(any("couldn't save the movie cache" in n for n in result.notes), result.notes)

    def test_enhanced_found_through_steam_libraries(self):
        """A different library (the Deck's SD card): libraryfolders.vdf lists it; POSIX paths seen through
        Proton get Wine's Z: drive."""
        game = Game(self.root, enhanced_where='library')
        library = self.root / 'sdcard'
        vdf = self.root / 'libraryfolders.vdf'
        vdf.write_text('"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n\t"1"\n\t{\n\t\t"path"\t\t"%s"\n'
                       '\t}\n}\n' % (str(self.root / 'nowhere').replace('\\', '\\\\'),
                                     str(library).replace('\\', '\\\\')), encoding='utf-8')
        self.assertIsNone(game.provide().enhanced)
        self.assertEqual(game.provide(vdfs=[vdf]).enhanced, game.enhanced_dir)
        self.assertEqual(hudmovie.library_paths('"path"  "/home/deck/.local/share/Steam"', proton=True),
                         [Path('Z:/home/deck/.local/share/Steam')])

    def test_enhanced_folder_setting_wins_and_a_wrong_one_is_reported(self):
        game = Game(self.root, enhanced_where='other')
        self.assertIsNone(game.provide().enhanced)
        result = game.provide(enhanced_setting=str(game.enhanced_dir))
        self.assertEqual((result.enhanced, result.art), (game.enhanced_dir, 'enhanced'))
        wrong = game.provide(enhanced_setting=str(self.root / 'missing'))
        self.assertEqual(wrong.art, 'original')
        self.assertTrue(any('Enhanced folder' in n for n in wrong.notes), wrong.notes)

    def test_without_enhanced_says_so(self):
        game = Game(self.root, enhanced_where=None)
        result = game.provide()
        self.assertEqual((result.art, result.enhanced), ('original', None))
        self.assertTrue(any('original art' in n for n in result.notes), result.notes)

    def test_known_inputs_are_recognised(self):
        """Decision 11 (as implemented): known input hashes identify the game files; an unknown set is reported,
        never refused (decision 4)."""
        game = Game(self.root)
        result = game.provide()
        self.assertFalse(result.recognised)
        self.assertTrue(any('unrecognised game files' in n for n in result.notes), result.notes)
        hashes = {name: hashlib.sha256(Path(p).read_bytes()).hexdigest() for name, p in result.inputs.items()}
        saved = dict(hudmovie.KNOWN_INPUTS)
        self.addCleanup(lambda: (hudmovie.KNOWN_INPUTS.clear(), hudmovie.KNOWN_INPUTS.update(saved)))
        hudmovie.KNOWN_INPUTS.update({digest: name for name, digest in hashes.items()})
        again = game.provide()
        self.assertTrue(again.recognised)
        self.assertFalse(any('unrecognised' in n for n in again.notes))

    def test_game_folder_from_the_settings_folder(self):
        self.assertEqual(hudmovie.game_dir(Path('C:/Games/Borderlands/sdk_mods/settings')), Path('C:/Games/Borderlands'))

    def test_steam_library_lists_start_with_the_games_own_library(self):
        game = Path('D:/SteamLibrary/steamapps/common/Borderlands')
        vdfs = hudmovie.default_vdfs(game)
        self.assertEqual(vdfs[0], Path('D:/SteamLibrary/steamapps/libraryfolders.vdf'))
        self.assertIn(Path('C:/Program Files (x86)/Steam/steamapps/libraryfolders.vdf'), vdfs)

    def test_package_listing_and_dependency_closure_commands(self):
        """The tools/ wrappers' commands run the mod's modules: upk lists exports, swfdeps a closure."""
        import contextlib
        import io
        upk = mod_source.load('upk')
        swfdeps = mod_source.load('swfdeps')
        pkg, gfx = self.root / 'GfxHUD.upk', self.root / 'status.gfx'
        hud, status, _ = fixture_inputs()
        pkg.write_bytes(package('FlashMovie.HUD', hud))
        gfx.write_bytes(status)
        out, argv = io.StringIO(), sys.argv
        try:
            with contextlib.redirect_stdout(out):
                sys.argv = ['upk.py', str(pkg), 'HUD']
                upk.main()
                sys.argv = ['swfdeps.py', str(gfx), '1154']
                swfdeps.main()
        finally:
            sys.argv = argv
        self.assertIn('FlashMovie.HUD', out.getvalue())
        self.assertIn('closure of [1154]: 5 characters', out.getvalue())
        with self.assertRaises(upk.PackageError):
            upk.movie(package('FlashMovie.HUD', b'not a movie'))


if __name__ == '__main__':
    unittest.main()
