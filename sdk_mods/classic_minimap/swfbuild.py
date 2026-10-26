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
        MinimapRecenter(rotate,offset)  UpdateThreats("u,v|u,v|...")
        MinimapCmd("op~args")  - the single entry point for the mod, via WillowGFxMovie.SingleArgInvokeS
    Classic GFxMovie.Invoke doesn't fill in its return value (calling it from Python crashed the game), so
    the mod only uses SingleArgInvokeS, and outcomes are left in _root.mmCreateMode / mmPing.
See PHASE1.md section 4 for the reasoning behind each piece.
"""
import os
import struct
import sys

try:        # inside the mod package: the in-game build (PLAN_V13)
    from . import as2asm, swfmerge
    from .swfdeps import DEFINES, SHAPES as SHAPE_CODES, Movie, read_tags, shape_bitmaps, skip_rect
except ImportError:     # a plain module: tools/ wrappers and the offline suites put this folder on sys.path
    import as2asm
    import swfmerge
    from swfdeps import DEFINES, SHAPES as SHAPE_CODES, Movie, read_tags, shape_bitmaps, skip_rect
Fn, function, tag = as2asm.Fn, as2asm.function, swfmerge.tag

SOURCE_ROOTS = (1132,)            # maps (zone art, landmark/player icon clips, dlcmap frame) in status_menu.gfx
MAPS_SPRITE = 1132
COPIED_FUNCTIONS = ('AddLandmark', 'UpdateLandmark', 'SetMapScale', 'InitDLC', 'SetMarkerColor')
MAP_ID = 1200
EXPORT_NAME = 'bl1mm_map'
ATTACH_DEPTH = 9000
FALLBACK_NAME = 'mmfallback'      # hidden timeline instance, used if attachMovie fails
FALLBACK_DEPTH = 600              # unused by the stock root timeline (1, 635..1295) and never removed
FALLBACK_OFFSCREEN = -20000
LANDMARK_SPRITE = 1066            # status menu landmark icons (frames objective .. questionmark)
# Vector art copied from the Enhanced HUD movie (E_HUD; PLAN_V08.md): shape id there -> id here. No bitmaps.
ENH_SHAPES = {108: 1301, 110: 1303, 179: 1305,     # turnin, newmission ("!"), north "N"
              81: 1307, 82: 1308,                   # minimap box (background + border), window (mask) (PLAN_V09)
              127: 1310}                            # threat marker: red diamond, black outline (E sprite 128)
TURNIN_ART, NEWMISSION_ART, NORTH_ART = 1302, 1304, 1306   # one-frame wrapper sprites (as E 109, 111, 180)
WINDOW_ART = 1309                 # wrapper placing the window shape top-left anchored (see map_sprite)
ENEMY_ART = 1311                  # one-frame wrapper for the threat marker (as E sprite 128), exported bl1mm_enemy
# Original art (PLAN_V13 decisions 5, 12-15), used when the Enhanced HUD movie isn't available. The glyph sprites
# take the ids of Enhanced's turnin / newmission / north shapes: art id -> (glyph, colour, outline text id); the
# coloured text is the next id. GLYPH_FONT copies the HUD's empty WillowBody record (the game's font library).
GLYPHS = {1301: ('X', 0x66FF00, 1312), 1303: ('!', 0xFFCC00, 1314), 1305: ('N', 0xFFFFFF, 1316)}  # E 108/110 colours
GLYPH_FONT = 1318
ORIGINAL_IDS = {1312, 1313, 1314, 1315, 1316, 1317, GLYPH_FONT}
GLYPH_SIZE = 28.0                 # font height (px): capitals about 20 px, like Enhanced's 19-21 px marks
GLYPH_BOX = 32.0
GLYPH_OUTLINE = 1.0
BOX_MARGIN = 5.0                  # a tight frame around the window (E shape 81's bounds include a clear margin, run 21)
BOX_FILL, BOX_LINE, BOX_LINE_WIDTH = (0x0B1624, 0xE6), (0x6A9AC8, 0xF0), 2.0
THREAT_ART_HALF, THREAT_LINE_WIDTH = 7.2, 1.5   # E shape 127 is 14.45 px across
# Enhanced's window (E shape 82, centred) and where its sprite 187 places things
WINDOW_LEFT, WINDOW_TOP, WINDOW_W, WINDOW_H = -103.95, -86.8, 207.95, 173.65
BOX_DEPTH, MASK_DEPTH, MAPS_DEPTH = 3, 4, 6
OBJECTIVE_ART = 1050              # classic objective diamond sprite (placed at 0.55 in the landmark frames)
EDGE_DEPTH = 100                  # north indicator; objective edge icons at EDGE_DEPTH + 1 + i
# Enhanced's edge-indicator path is the rectangle +-110 x +-92 around the window centre: on the box border,
# just outside the 207.95 x 173.65 window (E sprites 182/186 frame positions + their (0, -55) placement)
EDGE_OUT_X, EDGE_OUT_Y = 110.0 - WINDOW_W / 2, 92.0 - WINDOW_H / 2
OBJECTIVE_SCALE = 0.55
# Static half-size of an objective icon at _xscale 100: the diamond's base shape (1047, 45.1 units) at the
# landmark frame's 0.55. The art also has a pulsing ring (shape 1049 scaled 1.0 -> 2.2 over 12 frames), so the
# icon's live _width swings with the animation; the edge handoff must not use it (run 14 "wobble").
OBJECTIVE_HALF = 45.1 * OBJECTIVE_SCALE / 2
SOURCE_CLIPS = ('landmarks', 'players', 'enemy')   # maps' icon templates that AddLandmark duplicates
HUD_CLIPS = ('echo', 'quest', 'check1', 'check2', 'check3', 'check4', 'check5')   # p1 column we shift
THREAT_DEPTH = 1000


def top_level(d):
    """[(code, body, raw_bytes)] for the root timeline."""
    p = skip_rect(d, 8) + 4
    out = []
    while p < len(d):
        start = p
        hdr = struct.unpack_from('<H', d, p)[0]; p += 2
        code, ln = hdr >> 6, hdr & 0x3F
        if ln == 0x3F:
            ln = struct.unpack_from('<I', d, p)[0]; p += 4
        out.append((code, d[p:p + ln], d[start:p + ln])); p += ln
        if code == 0:
            break
    return out


def root_actions(d):
    """Decoded IR of every root-level DoAction in a movie."""
    return [as2asm.decode(b) for c, b, _ in top_level(d) if c == 12]


def copied_functions(status_menu):
    found = {}
    for ir in root_actions(status_menu):
        for name in COPIED_FUNCTIONS:
            f = as2asm.find_function(ir, name)
            if f and name not in found:
                found[name] = f
    missing = set(COPIED_FUNCTIONS) - set(found)
    if missing:
        raise SystemExit('status menu is missing root functions: %s' % sorted(missing))
    return found


def add_player_capture(addlandmark):
    """AddLandmark: before `return newClip`, remember the local player's icon clip.

    The classic native's FindPlayers adds the local player with frame "player" (buddies use buddy1..3),
    the same frame label the probe saw on MapObjects (clip_frame "player").
    """
    body = addlandmark['func']['body']
    assert as2asm.NAMES[body[-1]['op']] == 'Return', 'unexpected AddLandmark shape'
    a = Fn()
    a.if_not(('==', 'frame', ('s', 'player')), 'skip')
    a.setm('_root', 'mmPlayer', 'newObject')
    a.label('skip')
    snippet = a.build()
    # Branches inside the snippet are relative to its own start; shift them to the insertion point.
    at = len(body) - 3  # before: Push 'newClip' / GetVariable / Return
    for ins in snippet:
        if 'target' in ins:
            ins['target'] += at
    for ins in body[at:]:
        if 'target' in ins:
            ins['target'] += len(snippet)
    body[at:at] = snippet
    return addlandmark


def new_functions():
    fns = []

    # Classic GFxMovie.Invoke does not fill in its return value (in game it came back as Type=96 garbage),
    # so every function records its outcome in _root variables the mod reads with GetVariable*.
    a = Fn()  # MinimapCreate(x, y, scale): attach the exported map clip once, then place it
    a.if_not(('==', 'map', Ellipsis), 'have')
    a.setm('_root', 'mmCreateMode', ('s', 'attach'))
    a.do(('call', '_root', 'attachMovie', ('s', EXPORT_NAME), ('s', 'map'), ATTACH_DEPTH))
    a.if_not(('==', 'map', Ellipsis), 'have')
    # attachMovie failed: use the hidden timeline instance instead, renamed to `map` for the native
    a.setm('_root', 'mmCreateMode', ('s', 'none'))
    a.if_not(('!', ('==', FALLBACK_NAME, Ellipsis)), 'have')
    a.setm(FALLBACK_NAME, '_name', ('s', 'map'))
    a.setm('_root', 'mmCreateMode', ('s', 'fallback'))
    a.label('have')
    a.if_not(('!', ('==', 'map', Ellipsis)), 'out')
    a.setm('map', '_x', 'x').setm('map', '_y', 'y')
    a.setm('map', '_xscale', 'scale').setm('map', '_yscale', 'scale')
    a.setm('map', '_visible', True)
    a.label('out')
    a.ret(('!', ('==', 'map', Ellipsis)))
    fns.append(function('MinimapCreate', ('x', 'y', 'scale'), a))

    a = Fn()  # MinimapDestroy()
    a.if_not(('!', ('==', 'map', Ellipsis)), 'gone')
    a.if_not(('==', '_root.mmCreateMode', ('s', 'fallback')), 'remove')
    a.setm('map', '_visible', False)          # timeline instance: hide and give the name back
    a.setm('map', '_x', FALLBACK_OFFSCREEN).setm('map', '_y', FALLBACK_OFFSCREEN)
    a.setm('map', '_name', ('s', FALLBACK_NAME))
    a.jump('gone')
    a.label('remove')
    a.do(('call', 'map', 'removeMovieClip'))
    a.label('gone')
    a.setm('_root', 'mmPlayer', Ellipsis).setm('_root', 'mmThreats', Ellipsis)
    a.setm('_root', 'mmObjectives', Ellipsis).setm('_root', 'mmNorth', Ellipsis).setm('_root', 'mmEdges', Ellipsis)
    a.setm('_root', 'mmCreateMode', Ellipsis)
    a.ret(True)
    fns.append(function('MinimapDestroy', (), a))

    # MinimapCmd("op~arg~arg"): the only entry point the SDK mod calls. Python must not use
    # GFxMovie.Invoke: its ASValue return (with an FString) is never filled in by classic, and converting
    # that garbage crashed the game inside pyunrealsdk. WillowGFxMovie.SingleArgInvokeS is native, takes one
    # string and returns nothing. "~" separates fields; UpdateThreats' own payload uses "|" and ",".
    a = Fn()
    a.local('parts', ('call', 's', 'split', ('s', '~')))
    a.local('op', ('idx', 'parts', 0))
    a.local('n', ('mem', 'parts', 'length'))
    a.if_not(('==', 'op', ('s', 'create')), 'c_destroy')
    a.do(('fn', 'MinimapCreate', ('fn', 'Number', ('idx', 'parts', 1)), ('fn', 'Number', ('idx', 'parts', 2)),
          ('fn', 'Number', ('idx', 'parts', 3))))
    a.ret(True)
    a.label('c_destroy')
    a.if_not(('==', 'op', ('s', 'destroy')), 'c_clear')
    a.do(('fn', 'MinimapDestroy'))
    a.ret(True)
    a.label('c_clear')
    a.if_not(('==', 'op', ('s', 'clear')), 'c_recenter')
    a.do(('fn', 'MinimapClear'))
    a.ret(True)
    a.label('c_recenter')
    a.if_not(('==', 'op', ('s', 'recenter')), 'c_threats')
    a.do(('fn', 'MinimapRecenter', ('==', ('idx', 'parts', 1), ('s', '1')), ('fn', 'Number', ('idx', 'parts', 2))))
    a.ret(True)
    a.label('c_threats')
    a.if_not(('==', 'op', ('s', 'threats')), 'c_ping')
    a.if_not(('<', 1, 'n'), 'nothreats')
    a.do(('fn', 'UpdateThreats', ('idx', 'parts', 1)))
    a.ret(True)
    a.label('nothreats')
    a.do(('fn', 'UpdateThreats', ('s', '')))
    a.ret(True)
    a.label('c_ping')
    a.if_not(('==', 'op', ('s', 'ping')), 'c_tick')
    a.do(('fn', 'MinimapPing', ('idx', 'parts', 1)))
    a.ret(True)
    # Python-driven path (PLAN_DIRECT step A): the mod projects positions itself each tick.
    a.label('c_tick')        # tick~u~v~deg~rotate~offset: place the player icon, then centre/rotate
    a.if_not(('==', 'op', ('s', 'tick')), 'c_add')
    a.do(('fn', 'MinimapPlayer', ('fn', 'Number', ('idx', 'parts', 1)), ('fn', 'Number', ('idx', 'parts', 2)),
          ('fn', 'Number', ('idx', 'parts', 3))))
    a.do(('fn', 'MinimapRecenter', ('==', ('idx', 'parts', 4), ('s', '1')), ('fn', 'Number', ('idx', 'parts', 5))))
    a.do(('fn', 'MinimapEdges'))
    a.ret(True)
    a.label('c_add')         # add~clip~u~v~deg~frame[~rgb]: one landmark icon (static), optionally tinted
    a.if_not(('==', 'op', ('s', 'add')), 'c_frame')
    a.local('c', ('fn', 'AddLandmark', ('idx', 'parts', 1), ('fn', 'Number', ('idx', 'parts', 2)),
                  ('fn', 'Number', ('idx', 'parts', 3)), ('fn', 'Number', ('idx', 'parts', 4)), ('idx', 'parts', 5)))
    a.local('o', ('eval', 'c'))
    a.if_not('o', 'add_done')
    a.setm('o', '_visible', True)          # duplicates inherit the hidden source clip's _visible
    # Enhanced draws icons at its map clip's scale; ours sit in the unscaled `maps`, so scale them up
    a.if_not(('!', ('==', '_root.mmIconScale', Ellipsis)), 'add_noscale')
    a.setm('o', '_xscale', '_root.mmIconScale').setm('o', '_yscale', '_root.mmIconScale')
    a.label('add_noscale')
    # every icon, for MinimapRecenter's counter-rotation (Enhanced's iconPathArray / CancelOutIconRotation)
    a.if_not(('==', '_root.mmIcons', Ellipsis), 'add_haveicons')
    a.setm('_root', 'mmIcons', ('new', 'Array'))
    a.label('add_haveicons')
    a.do(('call', '_root.mmIcons', 'push', 'o'))
    # Enhanced tracks the objective icon for its edge indicator (currentObjectiveClip); we keep them all
    a.if_not(('==', ('idx', 'parts', 5), ('s', 'objective')), 'add_notobj')
    a.if_not(('==', '_root.mmObjectives', Ellipsis), 'add_havelist')
    a.setm('_root', 'mmObjectives', ('new', 'Array'))
    a.label('add_havelist')
    a.do(('call', '_root.mmObjectives', 'push', 'o'))
    a.label('add_notobj')
    # Classic's landmark art has no Enhanced turnin/newmission frames: the mod tints the objective diamond
    a.if_not(('<', 6, 'n'), 'add_done')
    a.setm('o', 'mmTint', ('fn', 'Number', ('idx', 'parts', 6)))       # edge indicator copies the tint
    a.do(('fn', 'MinimapTint', 'o', ('mem', 'o', 'mmTint')))
    a.label('add_done')
    a.ret(True)
    a.label('c_frame')       # frame~label: select the zone art directly
    a.if_not(('==', 'op', ('s', 'frame')), 'c_scale')
    a.do(('call', ('mem', 'map', 'maps'), 'gotoAndStop', ('idx', 'parts', 1)))
    a.ret(True)
    a.label('c_scale')       # scale~percent: zoom the zone art (icons are placed relative to it)
    a.if_not(('==', 'op', ('s', 'scale')), 'c_dock')
    a.do(('fn', 'SetMapScale', ('fn', 'Number', ('idx', 'parts', 1))))
    a.ret(True)
    a.label('c_dock')        # dock~a~b~c~d~tx~ty: place the map clip with a full (skewed) matrix
    a.if_not(('==', 'op', ('s', 'dock')), 'c_hud')
    a.do(('fn', 'MinimapDock', *[('fn', 'Number', ('idx', 'parts', i)) for i in range(1, 7)]))
    a.ret(True)
    a.label('c_hud')         # hud~mode~ex~ey~qx~qy~cx~cy~cdy~csx~csy: shift/restore the p1 column
    a.if_not(('==', 'op', ('s', 'hud')), 'c_iconscale')
    a.do(('fn', 'MinimapHudShift', *[('fn', 'Number', ('idx', 'parts', i)) for i in range(1, 11)]))
    a.ret(True)
    a.label('c_iconscale')   # iconscale~percent: size of icons created from now on, threat dots, edge icons
    a.if_not(('==', 'op', ('s', 'iconscale')), 'unknown')
    a.setm('_root', 'mmIconScale', ('fn', 'Number', ('idx', 'parts', 1)))
    a.ret(True)
    a.label('unknown')
    a.setm('_root', 'mmBadCmd', 's')
    a.ret(False)
    fns.append(function('MinimapCmd', ('s',), a))

    # MinimapTint(clip, rgb): tint by multiplying (white -> rgb, dark stays dark, alpha untouched). setRGB
    # painted every pixel one colour: the objective diamond lost its ring and centre and its faint 45-unit
    # glow square became a solid gold square (run 15).
    a = Fn()
    a.local('ct', ('new', 'Object'))
    a.setm('ct', 'ra', ('/', ('call', 'Math', 'floor', ('/', 'rgb', 65536)), 2.55))
    a.setm('ct', 'ga', ('/', ('%', ('call', 'Math', 'floor', ('/', 'rgb', 256)), 256), 2.55))
    a.setm('ct', 'ba', ('/', ('%', 'rgb', 256), 2.55))
    a.setm('ct', 'aa', 100).setm('ct', 'rb', 0).setm('ct', 'gb', 0).setm('ct', 'bb', 0).setm('ct', 'ab', 0)
    a.do(('call', ('new', 'Color', 'clip'), 'setTransform', 'ct'))
    a.ret(True)
    fns.append(function('MinimapTint', ('clip', 'rgb'), a))

    a = Fn()  # MinimapPlayer(u, v, deg): create the local player's icon once, then move/turn it
    a.if_not(('==', '_root.mmPlayer', Ellipsis), 'move')
    a.do(('fn', 'AddLandmark', ('s', 'map.maps.players'), 'u', 'v', 'deg', ('s', 'player')))   # sets mmPlayer
    a.if_not(('!', ('==', '_root.mmPlayer', Ellipsis)), 'noplayer')
    a.setm('_root.mmPlayer', '_visible', True)   # duplicate of the hidden players source clip
    a.if_not(('!', ('==', '_root.mmIconScale', Ellipsis)), 'noplayer')
    a.setm('_root.mmPlayer', '_xscale', '_root.mmIconScale').setm('_root.mmPlayer', '_yscale', '_root.mmIconScale')
    a.label('noplayer')
    a.ret(True)
    a.label('move')
    a.local('tm', ('mem', ('mem', 'map', 'maps'), 'themap'))
    a.local('p', '_root.mmPlayer')
    a.setm('p', '_x', ('+', ('mem', 'tm', '_x'), ('*', 'u', ('mem', 'tm', '_width'))))
    a.setm('p', '_y', ('+', ('mem', 'tm', '_y'), ('*', 'v', ('mem', 'tm', '_height'))))
    a.setm('p', '_rotation', 'deg')
    a.ret(True)
    fns.append(function('MinimapPlayer', ('u', 'v', 'deg'), a))

    # MinimapDock(a,b,c,d,tx,ty): Enhanced places its minimap in p1 with a sheared matrix (skew0 = 0.07 * sx,
    # like every right-column HUD element). attachMovie can't set a shear, so set transform.matrix; the
    # classic Scaleform runtime has flash.geom.Matrix/Transform (REA: PLAN_V07.md 3). Read it back; if the
    # runtime ignored it, fall back to position + scale without the shear. mmDockMode reports which.
    a = Fn()
    a.if_not(('!', ('==', 'map', Ellipsis)), 'nomap')
    a.local('m', ('newm', 'flash.geom', 'Matrix', 'a', 'b', 'c', 'd', 'tx', 'ty'))
    a.local('t', ('mem', 'map', 'transform'))
    a.if_not('t', 'plain')
    a.setm('t', 'matrix', 'm')
    a.local('r', ('mem', ('mem', 'map', 'transform'), 'matrix'))
    a.if_not('r', 'plain')
    a.setm('_root', 'mmDockB', ('mem', 'r', 'b'))
    for k in ('a', 'b', 'd', 'tx'):
        a.if_not(('<', ('call', 'Math', 'abs', ('-', ('mem', 'r', k), k)), 0.001), 'plain')
    a.setm('_root', 'mmDockMode', ('s', 'matrix'))
    a.ret(True)
    a.label('plain')
    a.setm('map', '_x', 'tx').setm('map', '_y', 'ty')
    a.setm('map', '_xscale', ('*', 'a', 100)).setm('map', '_yscale', ('*', 'd', 100))
    a.setm('_root', 'mmDockMode', ('s', 'plain'))
    a.ret(True)
    a.label('nomap')
    a.ret(False)
    fns.append(function('MinimapDock', ('a', 'b', 'c', 'd', 'tx', 'ty'), a))

    # MinimapHudShift(mode, ...): Enhanced's p<N>.UpdateEchoPosition moves the ECHO panel left of the
    # minimap; its layout also authors the quest title and checklist smaller/higher. Classic's are where the
    # map now sits, so: mode 2 = record the authored placements once per p1 instance (p1.mmOrig; a layout
    # switch creates a new p1), 1 = apply Enhanced's, 0 = restore. Only _x/_y/_xscale/_yscale are touched,
    # which keeps each clip's authored shear.
    a = Fn()
    a.local('p', '_root.p1')
    a.if_not(('!', ('==', 'p', Ellipsis)), 'nop1')
    a.if_not(('==', ('mem', 'p', 'mmOrig'), Ellipsis), 'have_orig')
    a.local('o', ('new', 'Object'))
    for n in HUD_CLIPS:
        a.if_not(('!', ('==', ('mem', 'p', n), Ellipsis)), 'rec_' + n)
        for prop, key in (('_x', 'x'), ('_y', 'y'), ('_xscale', 'sx'), ('_yscale', 'sy')):
            a.setm('o', '%s_%s' % (n, key), ('mem', ('mem', 'p', n), prop))
        a.label('rec_' + n)
    a.setm('p', 'mmOrig', 'o')
    a.label('have_orig')
    a.local('o', ('mem', 'p', 'mmOrig'))
    a.setm('_root', 'mmEchoX0', ('mem', 'o', 'echo_x'))
    a.if_not(('!', ('==', 'mode', 2)), 'done')
    for i, n in enumerate(HUD_CLIPS):
        k = ('mem', 'p', n)
        a.if_not(('!', ('==', k, Ellipsis)), 'next_' + n)
        a.if_not(('==', 'mode', 1), 'restore_' + n)
        if n == 'echo':
            a.setm(k, '_x', 'ex').setm(k, '_y', 'ey')
        elif n == 'quest':
            a.setm(k, '_x', 'qx').setm(k, '_y', 'qy')
        else:
            a.setm(k, '_xscale', 'csx').setm(k, '_yscale', 'csy')
            a.setm(k, '_x', 'cx').setm(k, '_y', ('+', 'cy', ('*', 'cdy', i - 2)))
        a.jump('next_' + n)
        a.label('restore_' + n)
        a.setm(k, '_xscale', ('mem', 'o', n + '_sx')).setm(k, '_yscale', ('mem', 'o', n + '_sy'))
        a.setm(k, '_x', ('mem', 'o', n + '_x')).setm(k, '_y', ('mem', 'o', n + '_y'))
        a.label('next_' + n)
    a.label('done')
    a.setm('_root', 'mmHudMode', 'mode')
    a.ret(True)
    a.label('nop1')
    a.ret(False)
    fns.append(function('MinimapHudShift', ('mode', 'ex', 'ey', 'qx', 'qy', 'cx', 'cy', 'cdy', 'csx', 'csy'), a))

    # MinimapEdges(): Enhanced's northMC / currentObjectiveMC (E_HUD Minimap class): an indicator on the window
    # edge in the direction of map north (always shown) and of each objective icon outside the window
    # (shown only then). The ray meets Enhanced's box-border rectangle; the visibility handoff uses the
    # actual window inset by half the icon extent (PLAN_V10).
    a = Fn()
    a.if_not(('!', ('==', 'map', Ellipsis)), 'e_out')
    a.local('mk', ('mem', 'map', 'mask'))
    a.local('ms', ('mem', 'map', 'maps'))
    a.local('isc', 1)
    a.if_not(('!', ('==', '_root.mmIconScale', Ellipsis)), 'e_isc')
    a.setv('isc', ('/', '_root.mmIconScale', 100))
    a.label('e_isc')
    a.local('hw', ('/', ('mem', 'mk', '_width'), 2))
    a.local('hh', ('/', ('mem', 'mk', '_height'), 2))
    a.local('cx', ('+', ('mem', 'mk', '_x'), 'hw'))
    a.local('cy', ('+', ('mem', 'mk', '_y'), 'hh'))
    a.local('ex', ('+', 'hw', EDGE_OUT_X))      # Enhanced's path: on the box border, around the window
    a.local('ey', ('+', 'hh', EDGE_OUT_Y))
    a.local('R', ('*', ('mem', 'ms', '_rotation'), 0.017453292519943295))
    a.local('c', ('call', 'Math', 'cos', 'R'))
    a.local('s', ('call', 'Math', 'sin', 'R'))
    a.local('k', ('/', ('mem', 'ms', '_xscale'), 100))

    def edge_point(tag):
        # t = distance factor along (dx, dy) to the box-border rectangle
        a.local('ax', ('call', 'Math', 'abs', 'dx'))
        a.local('ay', ('call', 'Math', 'abs', 'dy'))
        a.local('t', 1000000)
        a.if_not(('<', 0.000001, 'ax'), tag + '_ay')
        a.setv('t', ('/', 'ex', 'ax'))
        a.label(tag + '_ay')
        a.if_not(('<', 0.000001, 'ay'), tag + '_done')
        a.if_not(('<', ('/', 'ey', 'ay'), 't'), tag + '_done')
        a.setv('t', ('/', 'ey', 'ay'))
        a.label(tag + '_done')

    # north: map art "up" (0, -1) rotated by the maps rotation
    a.if_not(('==', '_root.mmNorth', Ellipsis), 'e_haven')
    a.setm('_root', 'mmNorth', ('call', 'map', 'attachMovie', ('s', 'bl1mm_north'), ('s', 'mmNorth'), EDGE_DEPTH))
    a.label('e_haven')
    a.local('nc', '_root.mmNorth')
    a.local('dx', 's')
    a.local('dy', ('-', 0, 'c'))
    edge_point('en')
    a.setm('nc', '_xscale', ('*', 'isc', 100)).setm('nc', '_yscale', ('*', 'isc', 100))
    a.setm('nc', '_x', ('+', 'cx', ('*', 'dx', 't'))).setm('nc', '_y', ('+', 'cy', ('*', 'dy', 't')))
    # objectives
    a.if_not(('==', '_root.mmEdges', Ellipsis), 'e_havepool')
    a.setm('_root', 'mmEdges', ('new', 'Array'))
    a.label('e_havepool')
    a.local('pool', '_root.mmEdges')
    a.local('list', '_root.mmObjectives')
    a.local('cnt', 0)
    a.if_not(('!', ('==', 'list', Ellipsis)), 'e_cnt')
    a.setv('cnt', ('mem', 'list', 'length'))
    a.label('e_cnt')
    a.local('i', 0)
    a.label('e_loop')
    a.if_not(('<', 'i', 'cnt'), 'e_hide')
    a.local('o', ('idx', 'list', 'i'))
    a.setv('dx', ('-', ('+', ('mem', 'ms', '_x'), ('*', 'k', ('-', ('*', ('mem', 'o', '_x'), 'c'), ('*', ('mem', 'o', '_y'), 's')))), 'cx'))
    a.setv('dy', ('-', ('+', ('mem', 'ms', '_y'), ('*', 'k', ('+', ('*', ('mem', 'o', '_x'), 's'), ('*', ('mem', 'o', '_y'), 'c')))), 'cy'))
    a.local('e', Ellipsis)                       # local on both branches (SetVariable alone would hit _root)
    a.if_not(('<', 'i', ('mem', 'pool', 'length')), 'e_new')
    a.setv('e', ('idx', 'pool', 'i'))
    a.jump('e_have')
    a.label('e_new')
    a.setv('e', ('call', 'map', 'attachMovie', ('s', 'bl1mm_objective'), ('+', ('s', 'mmEdge'), 'i'), ('+', EDGE_DEPTH + 1, 'i')))
    a.do(('call', 'pool', 'push', 'e'))
    a.if_not(('!', ('==', ('mem', 'o', 'mmTint'), Ellipsis)), 'e_have')
    a.do(('fn', 'MinimapTint', 'e', ('mem', 'o', 'mmTint')))
    a.label('e_have')
    a.setm('e', '_xscale', ('*', 'isc', OBJECTIVE_SCALE * 100)).setm('e', '_yscale', ('*', 'isc', OBJECTIVE_SCALE * 100))
    edge_point('eo')
    # PLAN_V10: the whole icon must fit the actual window. Keep the diamond on Enhanced's box path. The icon's
    # size comes from its scale, not its live _width, which pulses with the art (OBJECTIVE_HALF).
    a.local('r', ('*', ('*', OBJECTIVE_HALF, ('/', ('mem', 'o', '_xscale'), 100)), 'k'))
    a.if_not(('!', ('<', ('-', 'hw', 'r'), 'ax')), 'e_off')
    a.if_not(('!', ('<', ('-', 'hh', 'r'), 'ay')), 'e_off')
    a.setm('e', '_visible', False)
    a.setm('o', '_visible', True)
    a.jump('e_next')
    a.label('e_off')
    a.setm('e', '_x', ('+', 'cx', ('*', 'dx', 't'))).setm('e', '_y', ('+', 'cy', ('*', 'dy', 't')))
    a.setm('e', '_visible', True)
    a.setm('o', '_visible', False)
    a.label('e_next')
    a.setv('i', ('+', 'i', 1))
    a.jump('e_loop')
    a.label('e_hide')
    a.if_not(('<', 'i', ('mem', 'pool', 'length')), 'e_out')
    a.setm(('idx', 'pool', 'i'), '_visible', False)
    a.setv('i', ('+', 'i', 1))
    a.jump('e_hide')
    a.label('e_out')
    a.ret(True)
    fns.append(function('MinimapEdges', (), a))

    a = Fn()  # MinimapPing(v): side-effect probe, proves the patched root functions are callable
    a.setm('_root', 'mmPing', 'v')
    a.ret(True)
    fns.append(function('MinimapPing', ('v',), a))

    a = Fn()  # MinimapClear(): remove every dynamically created child of map.maps (icons, dots)
    a.local('ms', ('mem', 'map', 'maps'))
    a.if_not(('!', ('==', 'ms', Ellipsis)), 'done')
    a.local('d', ('-', ('call', 'ms', 'getNextHighestDepth'), 1))
    a.label('loop')
    a.if_not(('!', ('<', 'd', 0)), 'done')
    a.local('c', ('call', 'ms', 'getInstanceAtDepth', 'd'))
    a.if_not('c', 'next')
    a.do(('call', 'c', 'removeMovieClip'))
    a.label('next')
    a.setv('d', ('-', 'd', 1))
    a.jump('loop')
    a.label('done')
    # The zone frames place the icon source clips (landmarks: first frame "objective"; players: "player")
    # at the maps origin and never remove them. AddLandmark duplicates them; the originals must not show
    # (run 9: a stuck diamond and arrow). Enhanced's Minimap.SetMapFrame hides them the same way.
    a.if_not(('!', ('==', 'ms', Ellipsis)), 'hidden')
    for src in SOURCE_CLIPS:
        a.if_not(('!', ('==', ('mem', 'ms', src), Ellipsis)), 'h_' + src)
        a.setm(('mem', 'ms', src), '_visible', False)
        a.label('h_' + src)
    a.label('hidden')
    a.setm('_root', 'mmPlayer', Ellipsis).setm('_root', 'mmThreats', Ellipsis)
    a.setm('_root', 'mmObjectives', Ellipsis).setm('_root', 'mmIcons', Ellipsis)
    a.if_not(('!', ('==', '_root.mmEdges', Ellipsis)), 'c_noedges')   # edge icons: recreated (untinted) on demand
    a.local('ep', '_root.mmEdges')
    a.local('j', 0)
    a.label('c_edgeloop')
    a.if_not(('<', 'j', ('mem', 'ep', 'length')), 'c_edgesgone')
    a.do(('call', ('idx', 'ep', 'j'), 'removeMovieClip'))
    a.setv('j', ('+', 'j', 1))
    a.jump('c_edgeloop')
    a.label('c_edgesgone')
    a.setm('_root', 'mmEdges', Ellipsis)
    a.label('c_noedges')
    a.ret(True)
    fns.append(function('MinimapClear', (), a))

    a = Fn()  # MinimapRecenter(rotate, offset): keep the player icon at the mask centre
    a.local('p', '_root.mmPlayer')
    a.if_not(('!', ('==', 'p', Ellipsis)), 'nop')
    a.local('mk', ('mem', 'map', 'mask'))
    a.local('ms', ('mem', 'map', 'maps'))
    a.local('cx', ('+', ('mem', 'mk', '_x'), ('/', ('mem', 'mk', '_width'), 2)))
    a.local('cy', ('+', ('mem', 'mk', '_y'), ('/', ('mem', 'mk', '_height'), 2)))
    a.local('s', ('/', ('mem', 'ms', '_xscale'), 100))
    a.local('R', 0)
    a.if_not('rotate', 'norot')
    a.setv('R', ('-', ('fn', 'Number', 'offset'), ('mem', 'p', '_rotation')))
    a.label('norot')
    a.setm('ms', '_rotation', 'R')
    # every icon and threat marker stays upright while the map turns: Enhanced's CancelOutIconRotation sets
    # -currentRot on each clip of iconPathArray and threatsArray (run 23, PHASE3 3an)
    a.if_not(('!', ('==', '_root.mmIcons', Ellipsis)), 'r_noicons')
    a.local('ip', '_root.mmIcons')
    a.local('ii', 0)
    a.label('r_iconloop')
    a.if_not(('<', 'ii', ('mem', 'ip', 'length')), 'r_noicons')
    a.setm(('idx', 'ip', 'ii'), '_rotation', ('-', 0, 'R'))
    a.setv('ii', ('+', 'ii', 1))
    a.jump('r_iconloop')
    a.label('r_noicons')
    a.if_not(('!', ('==', '_root.mmThreats', Ellipsis)), 'r_nothreats')
    a.local('tp', '_root.mmThreats')
    a.local('ti', 0)
    a.label('r_threatloop')
    a.if_not(('<', 'ti', ('mem', 'tp', 'length')), 'r_nothreats')
    a.setm(('idx', 'tp', 'ti'), '_rotation', ('-', 0, 'R'))
    a.setv('ti', ('+', 'ti', 1))
    a.jump('r_threatloop')
    a.label('r_nothreats')
    a.local('ang', ('*', 'R', 0.017453292519943295))
    a.local('c', ('call', 'Math', 'cos', 'ang'))
    a.local('n', ('call', 'Math', 'sin', 'ang'))
    a.local('px', ('mem', 'p', '_x'))
    a.local('py', ('mem', 'p', '_y'))
    a.setm('ms', '_x', ('-', 'cx', ('*', 's', ('-', ('*', 'px', 'c'), ('*', 'py', 'n')))))
    a.setm('ms', '_y', ('-', 'cy', ('*', 's', ('+', ('*', 'px', 'n'), ('*', 'py', 'c')))))
    a.ret(True)
    a.label('nop')
    a.ret(False)
    fns.append(function('MinimapRecenter', ('rotate', 'offset'), a))

    a = Fn()  # UpdateThreats("u,v|u,v|..."): u,v are 0-1 across themap, like Enhanced's UpdateThreats
    a.local('ms', ('mem', 'map', 'maps'))
    a.if_not(('!', ('==', 'ms', Ellipsis)), 'out')
    a.local('tm', ('mem', 'ms', 'themap'))
    a.if_not(('==', '_root.mmThreats', Ellipsis), 'havepool')
    a.setm('_root', 'mmThreats', ('new', 'Array'))
    a.label('havepool')
    a.local('pool', '_root.mmThreats')
    a.local('items', ('call', 's', 'split', ('s', '|')))
    a.local('i', 0)
    a.local('k', 0)
    a.label('loop')
    a.if_not(('<', 'i', ('mem', 'items', 'length')), 'hide')
    a.local('it', ('idx', 'items', 'i'))
    a.if_not(('!', ('==', 'it', ('s', ''))), 'next')
    a.local('uv', ('call', 'it', 'split', ('s', ',')))
    a.if_not(('!', ('<', 'k', ('mem', 'pool', 'length'))), 'have')
    # Enhanced's threat art (E sprite 128: red diamond, black outline), as its UpdateThreats duplicates
    a.local('c', ('call', 'ms', 'attachMovie', ('s', 'bl1mm_enemy'), ('+', ('s', 'mmT'), 'k'), ('+', THREAT_DEPTH, 'k')))
    a.do(('call', 'pool', 'push', 'c'))
    a.label('have')
    a.local('c', ('idx', 'pool', 'k'))
    a.setm('c', '_x', ('+', ('mem', 'tm', '_x'), ('*', ('fn', 'Number', ('idx', 'uv', 0)), ('mem', 'tm', '_width'))))
    a.setm('c', '_y', ('+', ('mem', 'tm', '_y'), ('*', ('fn', 'Number', ('idx', 'uv', 1)), ('mem', 'tm', '_height'))))
    a.setm('c', '_rotation', ('-', 0, ('mem', 'ms', '_rotation')))   # stays a diamond (CancelOutIconRotation)
    a.setm('c', '_visible', True)
    a.if_not(('!', ('==', '_root.mmIconScale', Ellipsis)), 'dot_noscale')
    a.setm('c', '_xscale', '_root.mmIconScale').setm('c', '_yscale', '_root.mmIconScale')
    a.label('dot_noscale')
    a.setv('k', ('+', 'k', 1))
    a.label('next')
    a.setv('i', ('+', 'i', 1))
    a.jump('loop')
    a.label('hide')
    a.if_not(('<', 'k', ('mem', 'pool', 'length')), 'out')
    a.setm(('idx', 'pool', 'k'), '_visible', False)
    a.setv('k', ('+', 'k', 1))
    a.jump('hide')
    a.label('out')
    a.ret(True)
    fns.append(function('UpdateThreats', ('s',), a))
    return fns


def map_sprite():
    """bl1mm_map, laid out like Enhanced's minimap clip (E_HUD sprite 187, PLAN_V09): the box art behind,
    the window as a clip layer masking the zone art, classic's maps on top of the box. The window sprite is
    anchored at its top-left corner, so map.mask._x/_y/_width/_height give the window rectangle the
    centring and edge code use; the window itself is centred on the clip origin, as in Enhanced."""
    box = tag(26, bytes([0x02]) + struct.pack('<HH', BOX_DEPTH, ENH_SHAPES[81]))
    # PlaceObject2 field order: depth, character, matrix, name, clip depth
    mask = tag(26, bytes([0x40 | 0x20 | 0x04 | 0x02]) + struct.pack('<HH', MASK_DEPTH, WINDOW_ART)
               + translate_matrix(WINDOW_LEFT, WINDOW_TOP) + b'mask\0' + struct.pack('<H', MAPS_DEPTH))
    maps = tag(26, bytes([0x20 | 0x02]) + struct.pack('<HH', MAPS_DEPTH, MAPS_SPRITE) + b'maps\0')
    sprite = struct.pack('<HH', MAP_ID, 1) + box + mask + maps + tag(1, b'') + tag(0, b'')
    return tag(39, sprite)


def translate_matrix(tx, ty):
    """SWF MATRIX with only a translation (pixels)."""
    a, b = int(round(tx * 20)), int(round(ty * 20))
    n = max(a.bit_length(), b.bit_length(), (-a).bit_length(), (-b).bit_length()) + 1
    bits = '0' + '0' + format(n, '05b') + format(sb(a, n), '0%db' % n) + format(sb(b, n), '0%db' % n)
    bits += '0' * (-len(bits) % 8)
    return int(bits, 2).to_bytes(len(bits) // 8, 'big')


def sb(v, nbits):
    return v & ((1 << nbits) - 1)


def place_fallback():
    """PlaceObject2: MAP_ID as FALLBACK_NAME at FALLBACK_DEPTH, translated off-screen."""
    body = (bytes([0x26]) + struct.pack('<HH', FALLBACK_DEPTH, MAP_ID)
            + translate_matrix(FALLBACK_OFFSCREEN, FALLBACK_OFFSCREEN) + FALLBACK_NAME.encode() + b'\0')
    return tag(26, body)


def raw_id(raw):
    """Character id of a raw definition tag (header short or long form)."""
    return struct.unpack_from('<H', raw, 6 if struct.unpack_from('<H', raw, 0)[0] & 0x3F == 0x3F else 2)[0]


def wrapper_sprite(sid, child):
    """One-frame sprite placing `child` at depth 1, identity matrix (like E_HUD 109, 111, 180)."""
    return tag(39, struct.pack('<HH', sid, 1) + tag(26, bytes([0x02]) + struct.pack('<HH', 1, child))
               + tag(1, b'') + tag(0, b''))


def enhanced_art(enhanced):
    """Copy the Enhanced turnin / newmission / north vector shapes under ENH_SHAPES ids, plus wrappers."""
    found = {}

    def scan(tags):
        for code, body in tags:
            if code in SHAPE_CODES and len(body) >= 2 and struct.unpack_from('<H', body, 0)[0] in ENH_SHAPES:
                found.setdefault(struct.unpack_from('<H', body, 0)[0], (code, body))
            if code == 39:
                scan(read_tags(body, 4, len(body)))
    scan(read_tags(enhanced, skip_rect(enhanced, 8) + 4, len(enhanced)))
    missing = sorted(set(ENH_SHAPES) - set(found))
    if missing:
        raise SystemExit('Enhanced HUD movie lacks shapes %s' % missing)
    out = []
    for old, new in sorted(ENH_SHAPES.items()):
        code, body = found[old]
        if shape_bitmaps(code, body):
            raise SystemExit('Enhanced shape %d fills with bitmaps; refusing to copy' % old)
        out.append(tag(code, struct.pack('<H', new) + body[2:]))
    return out + art_wrappers()


def art_wrappers():
    """The one-frame wrappers around the art ids, whichever art fills them."""
    out = [wrapper_sprite(TURNIN_ART, ENH_SHAPES[108]), wrapper_sprite(NEWMISSION_ART, ENH_SHAPES[110]),
           wrapper_sprite(NORTH_ART, ENH_SHAPES[179]), wrapper_sprite(ENEMY_ART, ENH_SHAPES[127])]
    # the window shape is centred; its wrapper shifts it so the sprite's origin is the window's top-left
    out.append(tag(39, struct.pack('<HH', WINDOW_ART, 1)
                   + tag(26, bytes([0x06]) + struct.pack('<HH', 1, ENH_SHAPES[82])
                         + translate_matrix(-WINDOW_LEFT, -WINDOW_TOP))
                   + tag(1, b'') + tag(0, b'')))
    return out


class BitWriter:
    """MSB-first bit packing for SWF records (RECT, shape records)."""

    def __init__(self):
        self.bits = []

    def u(self, v, n):
        self.bits += [(v >> (n - 1 - i)) & 1 for i in range(n)]

    def s(self, v, n):
        self.u(v & ((1 << n) - 1), n)

    def data(self):
        bits = self.bits + [0] * (-len(self.bits) % 8)
        return bytes(int(''.join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8))


def signed_bits(*values):
    return max([1] + [int(v).bit_length() + 1 for v in values] + [int(-v).bit_length() + 1 for v in values])


def rect_bytes(x0, x1, y0, y1):
    """SWF RECT from pixel bounds."""
    v = [int(round(c * 20)) for c in (x0, x1, y0, y1)]
    n = signed_bits(*v)
    w = BitWriter()
    w.u(n, 5)
    for c in v:
        w.s(c, n)
    return w.data()


def rgba(colour, alpha=0xFF):
    return struct.pack('>I', colour)[1:] + bytes([alpha])


def polygon_shape(sid, points, fill, line=None):
    """DefineShape3: one closed polygon (clockwise on screen, so the fill is FillStyle1), optional outline.

    fill and line colours are RGBA bytes; line is (width in px, RGBA)."""
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    pad = line[0] / 2 if line else 0
    body = struct.pack('<H', sid) + rect_bytes(min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad)
    body += bytes([1, 0x00]) + fill
    body += bytes([1]) + struct.pack('<H', int(round(line[0] * 20))) + line[1] if line else bytes([0])
    w = BitWriter()
    w.u(1, 4)                                       # NumFillBits
    w.u(1 if line else 0, 4)                        # NumLineBits
    twips = [(int(round(x * 20)), int(round(y * 20))) for x, y in points]
    w.u(0, 1)                                       # StyleChangeRecord: line?, fill1, moveTo
    w.u(0, 1); w.u(1 if line else 0, 1); w.u(1, 1); w.u(0, 1); w.u(1, 1)
    n = signed_bits(*twips[0])
    w.u(n, 5); w.s(twips[0][0], n); w.s(twips[0][1], n)
    w.u(1, 1)                                       # FillStyle1 = 1
    if line:
        w.u(1, 1)                                   # LineStyle = 1
    for (ax, ay), (bx, by) in zip(twips, twips[1:] + twips[:1]):
        dx, dy = bx - ax, by - ay
        n = max(2, signed_bits(dx, dy))
        w.u(1, 1); w.u(1, 1); w.u(n - 2, 4)         # StraightEdgeRecord, NumBits
        w.u(1, 1); w.s(dx, n); w.s(dy, n)           # general line
    w.u(0, 6)                                       # EndShapeRecord
    return tag(32, body + w.data())


def font_record(hud, name='WillowBody'):
    """The HUD's own DefineFont3 record for `name`: empty, so text in it draws the game font library's glyphs."""
    for code, body in read_tags(hud, skip_rect(hud, 8) + 4, len(hud)):
        if code == 75 and body[5:5 + body[4]].rstrip(b'\0') == name.encode():
            return body
    raise SystemExit('HUD movie has no %s font' % name)


def glyph_text(tid, glyph, colour):
    """DefineEditText: one centred, read-only glyph in GLYPH_FONT. The box centres the glyph's capital height."""
    half, top = GLYPH_BOX / 2, -0.45 * GLYPH_SIZE
    return tag(37, struct.pack('<H', tid) + rect_bytes(-half, half, top, top + 1.25 * GLYPH_SIZE)
               + bytes([0x80 | 0x08 | 0x04 | 0x01, 0x20 | 0x10])    # HasText ReadOnly HasTextColor HasFont; HasLayout NoSelect
               + struct.pack('<HH', GLYPH_FONT, int(round(GLYPH_SIZE * 20))) + rgba(colour)
               + bytes([2]) + struct.pack('<HHHh', 0, 0, 0, 0)       # centred, no margins, indent or leading
               + b'\0' + glyph.encode('latin-1') + b'\0')


def glyph_sprite(sid, tid):
    """The glyph over four black copies offset by GLYPH_OUTLINE px: an outline without AS2 filters (decision 14)."""
    places = [tag(26, bytes([0x06]) + struct.pack('<HH', depth, tid) + translate_matrix(dx, dy))
              for depth, (dx, dy) in enumerate(((-GLYPH_OUTLINE, 0), (GLYPH_OUTLINE, 0), (0, -GLYPH_OUTLINE),
                                                (0, GLYPH_OUTLINE)), 1)]
    places.append(tag(26, bytes([0x02]) + struct.pack('<HH', 5, tid + 1)))
    return tag(39, struct.pack('<HH', sid, 1) + b''.join(places) + tag(1, b'') + tag(0, b''))


def original_art(hud):
    """Original art (PLAN_V13 decisions 5, 12-15) under the ids enhanced_art uses, when the Enhanced HUD movie
    isn't available: game font glyphs for the turn-in, new-mission and north marks; our own box, window and
    threat diamond, at the sizes of Enhanced's shapes so every layout constant holds."""
    font = font_record(hud)
    out = [tag(75, struct.pack('<H', GLYPH_FONT) + font[2:])]
    for sid, (glyph, colour, tid) in sorted(GLYPHS.items()):
        out += [glyph_text(tid, glyph, 0x000000), glyph_text(tid + 1, glyph, colour), glyph_sprite(sid, tid)]
    x0, x1, y0, y1 = WINDOW_LEFT, WINDOW_LEFT + WINDOW_W, WINDOW_TOP, WINDOW_TOP + WINDOW_H
    m = BOX_MARGIN
    out.append(polygon_shape(ENH_SHAPES[81], [(x0 - m, y0 - m), (x1 + m, y0 - m), (x1 + m, y1 + m), (x0 - m, y1 + m)],
                             rgba(*BOX_FILL), (BOX_LINE_WIDTH, rgba(*BOX_LINE))))
    out.append(polygon_shape(ENH_SHAPES[82], [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], rgba(0x223853)))
    h = THREAT_ART_HALF
    out.append(polygon_shape(ENH_SHAPES[127], [(0, -h), (h, 0), (0, h), (-h, 0)], rgba(0xFF0000),
                             (THREAT_LINE_WIDTH, rgba(0x000000))))
    return out + art_wrappers()


def landmark_frames(raw):
    """The landmark sprite plus Enhanced's frames 12/13 (turnin, newmission) as frames 11/12. Frame 10
    (questionmark) placed at depth 2 and removed depth 1, so 11 removes 2 and 12 removes 1."""
    ln = struct.unpack_from('<H', raw, 0)[0] & 0x3F
    p = 2
    if ln == 0x3F:
        ln = struct.unpack_from('<I', raw, 2)[0]; p = 6
    body = raw[p:p + ln]
    sid, frames = struct.unpack_from('<HH', body, 0)
    tags = [(c, b) for c, b in read_tags(body, 4, len(body)) if c != 0]
    extra = [(43, b'turnin\0'), (28, struct.pack('<H', 2)), (26, bytes([0x02]) + struct.pack('<HH', 1, TURNIN_ART)),
             (1, b''), (43, b'newmission\0'), (28, struct.pack('<H', 1)),
             (26, bytes([0x02]) + struct.pack('<HH', 1, NEWMISSION_ART)), (1, b'')]
    return tag(39, struct.pack('<HH', sid, frames + 2) + b''.join(tag(c, b) for c, b in tags + extra) + tag(0, b''))


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
            if code in DEFINES and len(body) >= 2 and struct.unpack_from('<H', body, 0)[0] in ids]
    assert len(defs) == len(ids), (len(defs), len(ids))
    new_ids = set(ENH_SHAPES.values()) | {TURNIN_ART, NEWMISSION_ART, NORTH_ART, WINDOW_ART, ENEMY_ART}
    if enhanced is None:
        new_ids |= ORIGINAL_IDS
    if new_ids & (set(ids) | set(hud_movie.defs) | {MAP_ID}):
        raise SystemExit('character id clash for the art: %s' % sorted(new_ids & (set(ids) | set(hud_movie.defs))))
    li = [i for i, raw in enumerate(defs) if raw_id(raw) == LANDMARK_SPRITE]
    assert len(li) == 1, 'landmark sprite %d not found' % LANDMARK_SPRITE
    defs[li[0]] = landmark_frames(defs[li[0]])
    art = enhanced_art(enhanced) if enhanced is not None else original_art(hud)
    defs = art + defs           # each definition only references earlier ones

    funcs = copied_functions(status_menu)
    add_player_capture(funcs['AddLandmark'])
    actions = [funcs[n] for n in COPIED_FUNCTIONS] + new_functions()
    do_action = tag(12, as2asm.encode(actions, end=True))
    exports = ((MAP_ID, EXPORT_NAME), (NORTH_ART, 'bl1mm_north'), (OBJECTIVE_ART, 'bl1mm_objective'),
               (ENEMY_ART, 'bl1mm_enemy'))
    export = tag(56, struct.pack('<H', len(exports)) + b''.join(struct.pack('<H', cid) + name.encode() + b'\0'
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


def main():
    if len(sys.argv) not in (4, 5):
        raise SystemExit('usage: swfbuild.py <HUD.gfx> <status_menu.gfx> <out.gfx> [<HUD_enhanced.gfx>]')
    hud, sm, out = sys.argv[1:4]
    enh = open(sys.argv[4], 'rb').read() if len(sys.argv) == 5 else None
    data, info = build(open(hud, 'rb').read(), open(sm, 'rb').read(), enh)
    open(out, 'wb').write(data)
    print('wrote %s (%d bytes); added %d characters (%d bytes of definitions), %d bytes total'
          % (out, len(data), info['characters'], info['definition_bytes'], info['added_bytes']))
    print('root functions: %s' % ', '.join(info['functions']))


if __name__ == '__main__':
    main()
