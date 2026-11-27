"""The player-built movie: our HUD movie assembled from the player's own game files (PLAN_V13, ADR 0004).

Reads classic's GfxHUD.upk and menus_ingame_redux.upk, plus Enhanced's GfxHUD.upk when it can be found, runs
swfbuild, and keeps the result in a movie cache under sdk_mods/settings/ keyed on every input's SHA-256, the
art choice and the mod version (decision 6). No game files ship with the mod.
"""
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:        # inside the mod package
    from . import swfbuild, upk
except ImportError:     # a plain module (tools/ wrappers, offline tests)
    import swfbuild
    import upk

INTERFACE = Path('WillowGame/CookedPC/Packages/Interface')
HUD_PACKAGE, MENUS_PACKAGE = 'GfxHUD.upk', 'menus_ingame_redux.upk'
ENHANCED_INPUT = "Enhanced's GfxHUD.upk"
HUD_MOVIE, MENUS_MOVIE = 'FlashMovie.HUD', 'FlashMovies.status_menu'
ENHANCED_FOLDER = 'BorderlandsGOTYEnhanced'
# One movie cache per "Use Enhanced artwork" choice, so switching back and forth doesn't rebuild (run 21)
CACHE_NAMES = {True: 'classic_minimap_hud.gfx', False: 'classic_minimap_hud_original.gfx'}
KEY_NAMES = {True: 'classic_minimap_hud.json', False: 'classic_minimap_hud_original.json'}
STEAM_VDFS = ('C:/Program Files (x86)/Steam/steamapps/libraryfolders.vdf',
              'C:/Program Files/Steam/steamapps/libraryfolders.vdf')
PROTON_VDFS = ('.local/share/Steam/steamapps/libraryfolders.vdf', '.steam/steam/steamapps/libraryfolders.vdf')
# Input files this version was checked against (decision 11): SHA-256 -> what it is. Since the build is
# deterministic, recognised inputs mean the player's movie matches ours; anything else is reported, not refused.
KNOWN_INPUTS = {
    '5c515c3ea119bcffbaf774657d58b995b41a4f0daf6d9f3291ca9fb14b93ea88': 'classic GfxHUD.upk (Steam, English)',
    '22c976774a3ec3748834df5d1be3a8f1881759dba304c664a0d9007e49384a14': 'classic menus_ingame_redux.upk (Steam, English)',
    '07db64f4853cd8d38f9de04cc46e0c95976156983da52002ca26f42bc66e6cb7': "Enhanced's GfxHUD.upk (Steam)",
}


class BuildFailed(Exception):
    """The classic inputs are missing or can't be built from; the minimap stays idle (decision 17)."""


@dataclass
class Result:
    data: bytes
    art: str                        # 'enhanced' or 'original'
    cached: bool
    seconds: float
    enhanced: Any                   # Enhanced's game folder, or None
    inputs: dict
    recognised: bool
    notes: list = field(default_factory=list)


def game_dir(settings_dir):
    """<Borderlands> from <Borderlands>/sdk_mods/settings."""
    return Path(settings_dir).parent.parent


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def describe(ex):
    return str(ex.code) if isinstance(ex, SystemExit) else '%s: %s' % (type(ex).__name__, ex)


def library_paths(text, proton=False):
    """Library folders listed in a Steam libraryfolders.vdf. Through Proton, POSIX paths are Wine's Z: drive."""
    out = []
    for raw in re.findall(r'"path"\s+"([^"]*)"', text):
        path = raw.replace('\\\\', '\\')
        out.append(Path('Z:' + path) if proton and path.startswith('/') else Path(path))
    return out


def default_vdfs(game, homes=Path('Z:/home')):
    """Where Steam lists its libraries: the game's own library, then Steam's usual places (Windows, Proton).
    `homes` is the folder of user home folders Proton's Wine sees (a parameter so a test can supply one)."""
    out = [Path(game).parents[1] / 'libraryfolders.vdf'] + [Path(p) for p in STEAM_VDFS]
    try:
        if homes.is_dir():
            out += [home / p for home in sorted(homes.iterdir()) for p in PROTON_VDFS]
    except OSError:
        pass
    return out


def find_enhanced(game, setting, vdfs):
    """Enhanced's game folder: the "Enhanced folder" setting, next to classic, then every Steam library."""
    notes = []

    def usable(folder):
        return (Path(folder) / INTERFACE / HUD_PACKAGE).is_file()
    if setting:
        if usable(setting):
            return Path(setting), notes
        notes.append('The Enhanced folder setting (%s) has no %s; looking elsewhere.' % (setting, INTERFACE / HUD_PACKAGE))
    candidates = [Path(game).parent / ENHANCED_FOLDER]
    for vdf in vdfs:
        try:
            text = Path(vdf).read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        candidates += [lib / 'steamapps' / 'common' / ENHANCED_FOLDER for lib in library_paths(text, os.name == 'nt')]
    for folder in candidates:
        try:
            if usable(folder):
                return folder, notes
        except OSError:
            continue
    return None, notes


def build_movie(hud_package, menus_package, enhanced_package, version):
    """(movie bytes, art, notes) from package bytes. Enhanced's art when its package is usable, else original art."""
    try:
        hud, menus = upk.movie(hud_package, HUD_MOVIE), upk.movie(menus_package, MENUS_MOVIE)
    except upk.PackageError as ex:
        raise BuildFailed("classic's HUD files can't be used (%s)" % ex) from None
    notes = []
    if enhanced_package is not None:
        try:
            return swfbuild.build(hud, menus, upk.movie(enhanced_package, HUD_MOVIE), version)[0], 'enhanced', []
        except (SystemExit, Exception) as ex:
            notes.append("Enhanced's HUD package couldn't be used (%s); using the original art." % describe(ex))
    try:
        return swfbuild.build(hud, menus, None, version)[0], 'original', notes
    except (SystemExit, Exception) as ex:
        raise BuildFailed("couldn't build the HUD movie from your game files (%s)" % describe(ex)) from None


def load_cache(settings, key, use_enhanced):
    try:
        meta = json.loads((settings / KEY_NAMES[use_enhanced]).read_text(encoding='utf-8'))
        data = (settings / CACHE_NAMES[use_enhanced]).read_bytes()
        if meta['key'] == key and meta['sha256'] == sha256(data) and meta['art'] in ('enhanced', 'original'):
            return data, meta['art'], list(meta.get('notes', []))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def save_cache(settings, key, use_enhanced, data, art, notes):
    (settings / CACHE_NAMES[use_enhanced]).write_bytes(data)
    meta = dict(key=key, sha256=sha256(data), art=art, notes=notes, size=len(data))
    (settings / KEY_NAMES[use_enhanced]).write_text(json.dumps(meta, indent=2) + '\n', encoding='utf-8')


def provide(game, settings, version, use_enhanced=True, enhanced_setting='', rebuild=False, vdfs=None):
    """The player-built movie: from the movie cache when its key still matches, otherwise built and saved."""
    started = time.time()
    game, settings = Path(game), Path(settings)
    inputs = {HUD_PACKAGE: game / INTERFACE / HUD_PACKAGE, MENUS_PACKAGE: game / INTERFACE / MENUS_PACKAGE}
    notes, enhanced = [], None
    if use_enhanced:
        enhanced, found = find_enhanced(game, enhanced_setting, default_vdfs(game) if vdfs is None else vdfs)
        notes += found
        if enhanced is None:
            notes.append("GOTY Enhanced wasn't found; using the original art.")
        else:
            inputs[ENHANCED_INPUT] = enhanced / INTERFACE / HUD_PACKAGE
    blobs = {}
    for name, path in list(inputs.items()):
        try:
            blobs[name] = path.read_bytes()
        except OSError as ex:
            if name != ENHANCED_INPUT:
                raise BuildFailed("can't read %s (%s)" % (path, ex.strerror or ex)) from None
            notes.append("Enhanced's HUD package at %s can't be read; using the original art." % path)
            del inputs[name]
            enhanced = None
    hashes = {name: sha256(data) for name, data in blobs.items()}
    recognised = all(digest in KNOWN_INPUTS for digest in hashes.values())
    if not recognised:
        notes.append('unrecognised game files (not the Steam files this version was checked against); built anyway.')
    key = sha256(json.dumps([version, use_enhanced, sorted(hashes.items())]).encode())
    cached = None if rebuild else load_cache(settings, key, use_enhanced)
    if cached is not None:
        data, art, saved_notes = cached
        return Result(data, art, True, time.time() - started, enhanced, inputs, recognised, notes + saved_notes)
    data, art, build_notes = build_movie(blobs[HUD_PACKAGE], blobs[MENUS_PACKAGE], blobs.get(ENHANCED_INPUT), version)
    notes += build_notes
    try:
        save_cache(settings, key, use_enhanced, data, art, build_notes)
    except OSError as ex:
        notes.append("couldn't save the movie cache (%s); it will be built again next time." % (ex.strerror or ex))
    return Result(data, art, False, time.time() - started, enhanced, inputs, recognised, notes)
