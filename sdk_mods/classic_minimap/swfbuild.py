"""Build the classic BL1 minimap HUD movie.

Usage: python -I tools/swfbuild.py <HUD.gfx> <status_menu.gfx> <out.gfx> <HUD_enhanced.gfx>

The Enhanced HUD movie (GfxHUD.upk of BorderlandsGOTYEnhanced, also from the user's own install) supplies
three small vector shapes: the turnin and newmission ("!") landmark icons and the north indicator (PLAN_V08).

Takes the stock classic HUD movie (from GfxHUD.upk) and the stock status-menu movie (from
menus_ingame_redux.upk), both extracted from the user's own install with tools/upkpatch.py, and writes a
HUD movie that additionally contains:

  * the status menu's `maps` clip tree (sprite 1132: the vector zone art, landmark/player icon clips and
    the dlcmap loader frame), in ids the stock HUD (ids 1-764) does not use;
  * a new sprite MAP_ID laid out like Enhanced's minimap clip (E_HUD sprite 187, PLAN_V09): Enhanced's
    box art (depth 3), its 207.95 x 173.65 window as a clip layer named `mask` (depth 4) and `maps`
    (depth 6), exported as "bl1mm_map". The SDK
    mod attaches it as _root.map via MinimapCreate(). In case attachMovie doesn't work under the game's
    Scaleform, one instance also sits on the root timeline as `mmfallback` (depth 600, 20000 px
    off-screen), which MinimapCreate renames to `map`. With the mod off, nothing is visible;
  * root functions, defined in a frame-1 DoAction:
      - called by the classic native WillowGFxHelperMap (copied from the status menu):
        AddLandmark(clip,x,y,r,frame)   (also records the local player's icon in _root.mmPlayer)
        UpdateLandmark(clip,x,y,r)  SetMapScale(scale)  InitDLC(frame,pkg)  SetMarkerColor(color,clip)
      - called by the SDK mod:
        MinimapCreate(x,y,scale)  MinimapDestroy()  MinimapClear()  MinimapPing(v)
        MinimapRecenter(rotate)  UpdateThreats("u,v|u,v|...")
        MinimapCmd("op~args")  - the single entry point for the mod, via WillowGFxMovie.SingleArgInvokeS
    Classic GFxMovie.Invoke doesn't fill in its return value (calling it from Python crashed the game), so
    the mod only uses SingleArgInvokeS, and outcomes are left in _root.mmCreateMode / mmPing.
See PHASE1.md section 4 for the reasoning behind each piece.
"""
import os
import struct
import sys

try:        # inside the mod package: the in-game build (PLAN_V13)
    from . import as2asm
    from . import swfmerge
    from .hudart import enhanced_art, landmark_frames, original_art, save_art
    from .hudlayout import (BOX_DEPTH, COPIED_FUNCTIONS, ENEMY_ART, ENH_SHAPES, EXPORT_NAME, FALLBACK_DEPTH,
                            FALLBACK_NAME, FALLBACK_OFFSCREEN, LANDMARK_SPRITE, MAPS_DEPTH, MAPS_SPRITE, MAP_ID,
                            MASK_DEPTH, NEWMISSION_ART, NORTH_ART, OBJECTIVE_ART, ORIGINAL_IDS, SAVE_ART,
                            SAVE_EXPORT, SAVE_IDS, SOURCE_ROOTS, TURNIN_ART, WINDOW_ART, WINDOW_LEFT, WINDOW_TOP)
    from .hudlayout import BOX_MARGIN, WINDOW_H, WINDOW_W  # noqa: F401  (re-exported: the suites import them from here)
    from .hudscript import add_player_capture, copied_functions, new_functions
    from .swfdeps import DEFINES, Movie
    from .swfrecords import (DO_ACTION, EXPORT_ASSETS, one_frame_sprite, place, raw_id, read_tags, skip_rect, tag,
                             top_level, translate_matrix, u16, words)  # noqa: F401
except ImportError:     # a plain module: tools/ wrappers and the offline suites put this folder on sys.path
    import as2asm
    import swfmerge
    from hudart import enhanced_art, landmark_frames, original_art, save_art
    from hudlayout import (BOX_DEPTH, COPIED_FUNCTIONS, ENEMY_ART, ENH_SHAPES, EXPORT_NAME, FALLBACK_DEPTH,
                           FALLBACK_NAME, FALLBACK_OFFSCREEN, LANDMARK_SPRITE, MAPS_DEPTH, MAPS_SPRITE, MAP_ID,
                           MASK_DEPTH, NEWMISSION_ART, NORTH_ART, OBJECTIVE_ART, ORIGINAL_IDS, SAVE_ART,
                           SAVE_EXPORT, SAVE_IDS, SOURCE_ROOTS, TURNIN_ART, WINDOW_ART, WINDOW_LEFT, WINDOW_TOP)
    from hudlayout import BOX_MARGIN, WINDOW_H, WINDOW_W  # noqa: F401  (re-exported: the suites import them from here)
    from hudscript import add_player_capture, copied_functions, new_functions
    from swfdeps import DEFINES, Movie
    from swfrecords import (DO_ACTION, EXPORT_ASSETS, one_frame_sprite, place, raw_id, read_tags, skip_rect, tag,
                            top_level, translate_matrix, u16, words)  # noqa: F401


def map_sprite():
    """bl1mm_map, laid out like Enhanced's minimap clip (E_HUD sprite 187, PLAN_V09): the box art behind,
    the window as a clip layer masking the zone art, classic's maps on top of the box. The window sprite is
    anchored at its top-left corner, so map.mask._x/_y/_width/_height give the window rectangle the
    centring and edge code use; the window itself is centred on the clip origin, as in Enhanced."""
    return one_frame_sprite(MAP_ID,
                            place(BOX_DEPTH, ENH_SHAPES[81]),
                            place(MASK_DEPTH, WINDOW_ART, translate_matrix(WINDOW_LEFT, WINDOW_TOP), 'mask', MAPS_DEPTH),
                            place(MAPS_DEPTH, MAPS_SPRITE, name='maps'))


def place_fallback():
    """PlaceObject2: MAP_ID as FALLBACK_NAME at FALLBACK_DEPTH, translated off-screen."""
    return place(FALLBACK_DEPTH, MAP_ID, translate_matrix(FALLBACK_OFFSCREEN, FALLBACK_OFFSCREEN), FALLBACK_NAME)


def core_version():
    """The mod version the block manifest is stamped with (PLAN_V12 decision 11)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pyproject.toml')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    return next(l.split('"')[1] for l in text.splitlines() if l.startswith('version'))


def shift_gradient_images(root, insert_at, added):
    """Keep classic's external gradient images on classic's own shapes.

    GFx numbers gradient fills in file order and keys DefineExternalGradient (1003) records by that number
    (classic: 14 fills, 14 records, ids 0-13). Our block goes in before root[insert_at] and brings its own
    gradient fills (Enhanced's box, the status-menu map art), which shifted every later classic gradient:
    the box drew classic's bar textures and the damage indicator lost its texture (PHASE3 run 14). Records
    numbered at or after the insertion point move up by the number of inserted fills; the inserted fills
    get no record and render as their own vector gradients."""
    before = swfmerge.gradient_total(root[:insert_at])
    if any(c == 1003 for c, _ in read_tags(added, 0, len(added))):
        raise SystemExit('inserted block carries its own external gradient records')
    return swfmerge.shift_gradients(root, before, swfmerge.describe_block(added)['gradients'])


def build(hud, status_menu, enhanced=None, version=None):
    """Our movie from the stock HUD and status-menu movies, with Enhanced's art when its HUD movie is given and
    original art otherwise. `version` stamps the block manifest (default: the mod's pyproject.toml; the in-game
    build passes __version__, since the .sdkmod is a zip)."""
    hud_movie, sm_movie = Movie(data=hud), Movie(data=status_menu)

    ids = sm_movie.closure(SOURCE_ROOTS)
    clash = sorted(set(ids) & set(hud_movie.defs)) + ([MAP_ID] if MAP_ID in hud_movie.defs or MAP_ID in ids else [])
    if clash:
        raise SystemExit('character id clash: %s' % clash[:10])
    undefined = [c for c in ids if c not in sm_movie.defs]
    if undefined:
        raise SystemExit('status menu closure has undefined ids: %s' % undefined)

    # Definitions in their original order (each one only references earlier ones).
    defs = [raw for code, body, raw in top_level(status_menu)
            if code in DEFINES and len(body) >= 2 and u16(body, 0) in ids]
    assert len(defs) == len(ids), (len(defs), len(ids))
    new_ids = set(ENH_SHAPES.values()) | {TURNIN_ART, NEWMISSION_ART, NORTH_ART, WINDOW_ART, ENEMY_ART} | SAVE_IDS
    if enhanced is None:
        new_ids |= ORIGINAL_IDS
    if new_ids & (set(ids) | set(hud_movie.defs) | {MAP_ID}):
        raise SystemExit('character id clash for the art: %s' % sorted(new_ids & (set(ids) | set(hud_movie.defs))))
    li = [i for i, raw in enumerate(defs) if raw_id(raw) == LANDMARK_SPRITE]
    assert len(li) == 1, 'landmark sprite %d not found' % LANDMARK_SPRITE
    defs[li[0]] = landmark_frames(defs[li[0]])
    art = enhanced_art(enhanced) if enhanced is not None else original_art(hud)
    defs = art + save_art() + defs           # each definition only references earlier ones

    funcs = copied_functions(status_menu)
    add_player_capture(funcs['AddLandmark'])
    actions = [funcs[n] for n in COPIED_FUNCTIONS] + new_functions()
    do_action = tag(DO_ACTION, as2asm.encode(actions, end=True))
    exports = ((MAP_ID, EXPORT_NAME), (NORTH_ART, 'bl1mm_north'), (OBJECTIVE_ART, 'bl1mm_objective'),
               (ENEMY_ART, 'bl1mm_enemy'), (SAVE_ART, SAVE_EXPORT))
    export = tag(EXPORT_ASSETS, words(len(exports)) + b''.join(words(cid) + name.encode() + b'\0'
                                                               for cid, name in exports))
    added = b''.join(defs) + map_sprite() + export + place_fallback() + do_action

    root = top_level(hud)
    first_show = next(i for i, (c, _, _) in enumerate(root) if c == 1)
    root = shift_gradient_images(root, first_show, added)
    head = hud[:skip_rect(hud, 8) + 4]
    manifest = swfmerge.manifest_tag(version or core_version(), root[:first_show], added)   # for the runtime merge
    out = bytearray(head + b''.join(r for _, _, r in root[:first_show]) + manifest + added
                    + b''.join(r for _, _, r in root[first_show:]))
    trailing = hud[len(head) + sum(len(r) for _, _, r in root):]
    out += trailing
    struct.pack_into('<I', out, 4, len(out))
    return bytes(out), dict(characters=len(ids), definition_bytes=sum(len(x) for x in defs),
                            functions=[a['func']['name'] for a in actions], added_bytes=len(added))


def read_file(path):
    with open(path, 'rb') as f:
        return f.read()


def main():
    if len(sys.argv) not in (4, 5):
        raise SystemExit('usage: swfbuild.py <HUD.gfx> <status_menu.gfx> <out.gfx> [<HUD_enhanced.gfx>]')
    hud, sm, out = sys.argv[1:4]
    enh = read_file(sys.argv[4]) if len(sys.argv) == 5 else None
    data, info = build(read_file(hud), read_file(sm), enh)
    with open(out, 'wb') as f:
        f.write(data)
    print('wrote %s (%d bytes); added %d characters (%d bytes of definitions), %d bytes total'
          % (out, len(data), info['characters'], info['definition_bytes'], info['added_bytes']))
    print('root functions: %s' % ', '.join(info['functions']))


if __name__ == '__main__':
    main()
