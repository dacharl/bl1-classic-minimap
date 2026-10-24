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
import struct
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import as2asm  # noqa: E402
from as2asm import Fn, function  # noqa: E402
from swfdeps import DEFINES, SHAPES as SHAPE_CODES, Movie, read_tags, shape_bitmaps, skip_rect  # noqa: E402

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
              81: 1307, 82: 1308}                   # minimap box (background + border), window (mask) (PLAN_V09)
TURNIN_ART, NEWMISSION_ART, NORTH_ART = 1302, 1304, 1306   # one-frame wrapper sprites (as E 109, 111, 180)
WINDOW_ART = 1309                 # wrapper placing the window shape top-left anchored (see map_sprite)
# Enhanced's window (E shape 82, centred) and where its sprite 187 places things
WINDOW_LEFT, WINDOW_TOP, WINDOW_W, WINDOW_H = -103.95, -86.8, 207.95, 173.65
BOX_DEPTH, MASK_DEPTH, MAPS_DEPTH = 3, 4, 6
OBJECTIVE_ART = 1050              # classic objective diamond sprite (placed at 0.55 in the landmark frames)
EDGE_DEPTH = 100                  # north indicator; objective edge icons at EDGE_DEPTH + 1 + i
# Enhanced's edge-indicator path is the rectangle +-110 x +-92 around the window centre: on the box border,
# just outside the 207.95 x 173.65 window (E sprites 182/186 frame positions + their (0, -55) placement)
EDGE_OUT_X, EDGE_OUT_Y = 110.0 - WINDOW_W / 2, 92.0 - WINDOW_H / 2
OBJECTIVE_SCALE = 0.55
SOURCE_CLIPS = ('landmarks', 'players', 'enemy')   # maps' icon templates that AddLandmark duplicates
HUD_CLIPS = ('echo', 'quest', 'check1', 'check2', 'check3', 'check4', 'check5')   # p1 column we shift
THREAT_DEPTH = 1000
THREAT_COLOR = 0xFF2A2A
THREAT_HALF = 5


def tag(code, body):
    if len(body) < 0x3F and code not in (6, 21, 35, 20, 36, 90):
        return struct.pack('<H', (code << 6) | len(body)) + body
    return struct.pack('<HI', (code << 6) | 0x3F, len(body)) + body


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
    a.do(('call', ('new', 'Color', 'o'), 'setRGB', ('mem', 'o', 'mmTint')))
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
    # (shown only then). Enhanced's 360-frame sprites trace its own 220x180 frame; here the point is the ray
    # from the mask centre meeting the mask rectangle (inset by half an icon), so it fits our window.
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
        # t = distance factor along (dx, dy) to the inset rectangle
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
    a.do(('call', ('new', 'Color', 'e'), 'setRGB', ('mem', 'o', 'mmTint')))
    a.label('e_have')
    a.setm('e', '_xscale', ('*', 'isc', OBJECTIVE_SCALE * 100)).setm('e', '_yscale', ('*', 'isc', OBJECTIVE_SCALE * 100))
    edge_point('eo')
    # Hand the marker over at the inset border: inside, the objective's own icon shows; past it, only the
    # edge diamond does. Both sit on the same spot at t = 1, so one marker slides onto the edge instead of
    # a clipped icon plus a diamond (run 12 "double waypoint").
    a.if_not(('<', 1, 't'), 'e_off')             # t > 1: the icon itself is inside the inset window
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
    a.setm('_root', 'mmObjectives', Ellipsis)
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
    a.local('c', ('call', 'ms', 'createEmptyMovieClip', ('+', ('s', 'mmT'), 'k'), ('+', THREAT_DEPTH, 'k')))
    a.do(('call', 'c', 'beginFill', THREAT_COLOR, 100))
    a.do(('call', 'c', 'moveTo', -THREAT_HALF, -THREAT_HALF))
    a.do(('call', 'c', 'lineTo', THREAT_HALF, -THREAT_HALF))
    a.do(('call', 'c', 'lineTo', THREAT_HALF, THREAT_HALF))
    a.do(('call', 'c', 'lineTo', -THREAT_HALF, THREAT_HALF))
    a.do(('call', 'c', 'lineTo', -THREAT_HALF, -THREAT_HALF))
    a.do(('call', 'c', 'endFill'))
    a.do(('call', 'pool', 'push', 'c'))
    a.label('have')
    a.local('c', ('idx', 'pool', 'k'))
    a.setm('c', '_x', ('+', ('mem', 'tm', '_x'), ('*', ('fn', 'Number', ('idx', 'uv', 0)), ('mem', 'tm', '_width'))))
    a.setm('c', '_y', ('+', ('mem', 'tm', '_y'), ('*', ('fn', 'Number', ('idx', 'uv', 1)), ('mem', 'tm', '_height'))))
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
    out += [wrapper_sprite(TURNIN_ART, ENH_SHAPES[108]), wrapper_sprite(NEWMISSION_ART, ENH_SHAPES[110]),
            wrapper_sprite(NORTH_ART, ENH_SHAPES[179])]
    # the window shape is centred; its wrapper shifts it so the sprite's origin is the window's top-left
    out.append(tag(39, struct.pack('<HH', WINDOW_ART, 1)
                   + tag(26, bytes([0x06]) + struct.pack('<HH', 1, ENH_SHAPES[82])
                         + translate_matrix(-WINDOW_LEFT, -WINDOW_TOP))
                   + tag(1, b'') + tag(0, b'')))
    return out


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


def build(hud, status_menu, enhanced):
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
    new_ids = set(ENH_SHAPES.values()) | {TURNIN_ART, NEWMISSION_ART, NORTH_ART, WINDOW_ART}
    if new_ids & (set(ids) | set(hud_movie.defs) | {MAP_ID}):
        raise SystemExit('character id clash for Enhanced art: %s' % sorted(new_ids & (set(ids) | set(hud_movie.defs))))
    li = [i for i, raw in enumerate(defs) if raw_id(raw) == LANDMARK_SPRITE]
    assert len(li) == 1, 'landmark sprite %d not found' % LANDMARK_SPRITE
    defs[li[0]] = landmark_frames(defs[li[0]])
    defs = enhanced_art(enhanced) + defs           # each definition only references earlier ones

    funcs = copied_functions(status_menu)
    add_player_capture(funcs['AddLandmark'])
    actions = [funcs[n] for n in COPIED_FUNCTIONS] + new_functions()
    do_action = tag(12, as2asm.encode(actions, end=True))
    export = tag(56, struct.pack('<H', 3) + b''.join(struct.pack('<H', cid) + name.encode() + b'\0' for cid, name in
                                                     ((MAP_ID, EXPORT_NAME), (NORTH_ART, 'bl1mm_north'),
                                                      (OBJECTIVE_ART, 'bl1mm_objective'))))
    added = b''.join(defs) + map_sprite() + export + place_fallback() + do_action

    root = top_level(hud)
    first_show = next(i for i, (c, _, _) in enumerate(root) if c == 1)
    head = hud[:skip_rect(hud, 8) + 4]
    out = bytearray(head + b''.join(r for _, _, r in root[:first_show]) + added
                    + b''.join(r for _, _, r in root[first_show:]))
    trailing = hud[len(head) + sum(len(r) for _, _, r in root):]
    out += trailing
    struct.pack_into('<I', out, 4, len(out))
    return bytes(out), dict(characters=len(ids), definition_bytes=sum(len(x) for x in defs),
                            functions=[a['func']['name'] for a in actions], added_bytes=len(added))


def main():
    hud, sm, out, enh = sys.argv[1:5]
    data, info = build(open(hud, 'rb').read(), open(sm, 'rb').read(), open(enh, 'rb').read())
    open(out, 'wb').write(data)
    print('wrote %s (%d bytes); added %d characters (%d bytes of definitions), %d bytes total'
          % (out, len(data), info['characters'], info['definition_bytes'], info['added_bytes']))
    print('root functions: %s' % ', '.join(info['functions']))


if __name__ == '__main__':
    main()
