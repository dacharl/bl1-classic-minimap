"""The root functions the minimap movie carries: the ones copied from the status menu (called by the
classic native helper) and the ones the SDK mod calls through MinimapCmd, written as AS2 and assembled
with as2asm (PHASE1 section 4).
"""
try:        # inside the mod package: the in-game build (PLAN_V13)
    from . import as2asm
    from .hudlayout import (ATTACH_DEPTH, COPIED_FUNCTIONS, EDGE_DEPTH, EDGE_OUT_X, EDGE_OUT_Y, EXPORT_NAME,
                            FALLBACK_NAME, FALLBACK_OFFSCREEN, HUD_ARGS, HUD_CLIPS, OBJECTIVE_HALF, OBJECTIVE_SCALE,
                            SAVE_ART_SIZE, SAVE_DEPTH, SAVE_EXPORT, SOURCE_CLIPS, THREAT_DEPTH)
    from .swfrecords import DO_ACTION, top_level
except ImportError:     # a plain module: tools/ wrappers and the offline suites put this folder on sys.path
    import as2asm
    from hudlayout import (ATTACH_DEPTH, COPIED_FUNCTIONS, EDGE_DEPTH, EDGE_OUT_X, EDGE_OUT_Y, EXPORT_NAME,
                           FALLBACK_NAME, FALLBACK_OFFSCREEN, HUD_ARGS, HUD_CLIPS, OBJECTIVE_HALF, OBJECTIVE_SCALE,
                           SAVE_ART_SIZE, SAVE_DEPTH, SAVE_EXPORT, SOURCE_CLIPS, THREAT_DEPTH)
    from swfrecords import DO_ACTION, top_level
Fn, function = as2asm.Fn, as2asm.function


def root_actions(d):
    """Decoded IR of every root-level DoAction in a movie."""
    return [as2asm.decode(b) for c, b, _ in top_level(d) if c == DO_ACTION]


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


def minimap_create():
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
    # the game can reset p1's column at any moment (run 25): check every movie frame, before it's drawn,
    # instead of waiting for the mod's tick (which still calls it too)
    a.setm('map', 'onEnterFrame', 'MinimapHudKeep')
    a.label('out')
    a.ret(('!', ('==', 'map', Ellipsis)))
    return function('MinimapCreate', ('x', 'y', 'scale'), a)


def minimap_destroy():
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
    a.if_not(('!', ('==', '_root.mmsave', Ellipsis)), 'nosave')        # PLAN_V15 save indicator
    a.do(('call', '_root.mmsave', 'removeMovieClip'))
    a.label('nosave')
    a.setm('_root', 'mmSaveMode', Ellipsis)
    a.setm('_root', 'mmPlayer', Ellipsis).setm('_root', 'mmThreats', Ellipsis)
    a.setm('_root', 'mmObjectives', Ellipsis).setm('_root', 'mmNorth', Ellipsis).setm('_root', 'mmEdges', Ellipsis)
    a.setm('_root', 'mmCreateMode', Ellipsis)
    a.ret(True)
    return function('MinimapDestroy', (), a)


def minimap_cmd():
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
    a.do(('fn', 'MinimapRecenter', ('==', ('idx', 'parts', 1), ('s', '1'))))
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
    a.if_not(('==', 'op', ('s', 'ping')), 'c_save')
    a.do(('fn', 'MinimapPing', ('idx', 'parts', 1)))
    a.ret(True)
    # Python-driven path (PLAN_DIRECT step A): the mod projects positions itself each tick.
    a.label('c_save')        # save~show~x~y~size~alpha: our save indicator (PLAN_V15)
    a.if_not(('==', 'op', ('s', 'save')), 'c_tick')
    a.do(('fn', 'MinimapSave', ('fn', 'Number', ('idx', 'parts', 1)), ('fn', 'Number', ('idx', 'parts', 2)),
          ('fn', 'Number', ('idx', 'parts', 3)), ('fn', 'Number', ('idx', 'parts', 4)),
          ('fn', 'Number', ('idx', 'parts', 5))))
    a.ret(True)
    a.label('c_tick')        # tick~u~v~deg~rotate: place the player icon, then centre/rotate
    a.if_not(('==', 'op', ('s', 'tick')), 'c_add')
    a.do(('fn', 'MinimapPlayer', ('fn', 'Number', ('idx', 'parts', 1)), ('fn', 'Number', ('idx', 'parts', 2)),
          ('fn', 'Number', ('idx', 'parts', 3))))
    a.do(('fn', 'MinimapRecenter', ('==', ('idx', 'parts', 4), ('s', '1'))))
    a.do(('fn', 'MinimapEdges'))
    a.do(('fn', 'MinimapHudKeep'))
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
    return function('MinimapCmd', ('s',), a)


def minimap_tint():
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
    return function('MinimapTint', ('clip', 'rgb'), a)


def minimap_player():
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
    return function('MinimapPlayer', ('u', 'v', 'deg'), a)


def minimap_dock():
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
    return function('MinimapDock', ('a', 'b', 'c', 'd', 'tx', 'ty'), a)


def minimap_hud_shift():
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
    for v in HUD_ARGS:
        a.setm('_root', 'mmHud_' + v, v)          # for MinimapHudKeep
    a.ret(True)
    a.label('nop1')
    a.ret(False)
    return function('MinimapHudShift', ('mode', *HUD_ARGS), a)


def minimap_hud_keep():
    # MinimapHudKeep (every tick): the game re-plays p1's first frame now and then (run 25, Deck: F7 read the
    # shift on but echo back at its authored x), which puts the column back where the map sits. Re-apply the
    # shift when echo isn't where it put it, and count it in mmHudFixes for F7.
    a = Fn()
    a.if_not(('==', '_root.mmHudMode', 1), 'keep_done')
    a.local('d', ('-', ('mem', ('mem', '_root.p1', 'echo'), '_x'), '_root.mmHud_ex'))
    a.if_not(('!', ('<', 'd', -0.5)), 'keep_fix')
    a.if_not(('<', 0.5, 'd'), 'keep_done')
    a.label('keep_fix')
    a.do(('fn', 'MinimapHudShift', 1, *['_root.mmHud_' + v for v in HUD_ARGS]))
    a.if_not(('==', '_root.mmHudFixes', Ellipsis), 'keep_count')
    a.setm('_root', 'mmHudFixes', 0)
    a.label('keep_count')
    a.setm('_root', 'mmHudFixes', ('+', '_root.mmHudFixes', 1))
    a.label('keep_done')
    a.ret(True)
    return function('MinimapHudKeep', (), a)


def minimap_save():
    # MinimapSave(show, x, y, size, alpha), PLAN_V15: our save indicator, attached once above the map as
    # _root.mmsave, placed and scaled so its SAVE_ART_SIZE art is `size` px. The mod drives `alpha` every tick from
    # the engine's real-time clock, in step with the native icon's material pulse.
    a = Fn()
    a.local('s', '_root.mmsave')
    a.if_not(('==', 's', Ellipsis), 'have')
    a.if_not(('!', ('==', 'show', 0)), 'out')        # nothing to hide
    a.do(('call', '_root', 'attachMovie', ('s', SAVE_EXPORT), ('s', 'mmsave'), SAVE_DEPTH))
    a.local('s', '_root.mmsave')
    a.if_not(('!', ('==', 's', Ellipsis)), 'fail')
    a.label('have')
    a.setm('s', '_visible', ('!', ('==', 'show', 0)))
    a.setm('s', '_x', 'x').setm('s', '_y', 'y')
    a.local('k', ('*', ('/', 'size', SAVE_ART_SIZE), 100))
    a.setm('s', '_xscale', 'k').setm('s', '_yscale', 'k')
    a.setm('s', '_alpha', 'alpha')
    a.setm('_root', 'mmSaveMode', 'show')
    a.label('out')
    a.ret(True)
    a.label('fail')
    a.setm('_root', 'mmSaveMode', -1)                 # attachMovie failed
    a.ret(False)
    return function('MinimapSave', ('show', 'x', 'y', 'size', 'alpha'), a)


def minimap_edges():
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
    return function('MinimapEdges', (), a)


def minimap_ping():
    a = Fn()  # MinimapPing(v): side-effect probe, proves the patched root functions are callable
    a.setm('_root', 'mmPing', 'v')
    a.ret(True)
    return function('MinimapPing', ('v',), a)


def minimap_clear():
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
    return function('MinimapClear', (), a)


def minimap_recenter():
    a = Fn()  # MinimapRecenter(rotate): keep the player icon at the mask centre
    a.local('p', '_root.mmPlayer')
    a.if_not(('!', ('==', 'p', Ellipsis)), 'nop')
    a.local('mk', ('mem', 'map', 'mask'))
    a.local('ms', ('mem', 'map', 'maps'))
    a.local('cx', ('+', ('mem', 'mk', '_x'), ('/', ('mem', 'mk', '_width'), 2)))
    a.local('cy', ('+', ('mem', 'mk', '_y'), ('/', ('mem', 'mk', '_height'), 2)))
    a.local('s', ('/', ('mem', 'ms', '_xscale'), 100))
    a.local('R', 0)
    a.if_not('rotate', 'norot')
    a.setv('R', ('-', 0, ('mem', 'p', '_rotation')))
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
    return function('MinimapRecenter', ('rotate',), a)


def update_threats():
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
    return function('UpdateThreats', ('s',), a)


ROOT_BUILDERS = (minimap_create, minimap_destroy, minimap_cmd,
                 minimap_tint, minimap_player, minimap_dock, minimap_hud_shift, minimap_hud_keep, minimap_save,
                 minimap_edges, minimap_ping, minimap_clear, minimap_recenter, update_threats)


def new_functions():
    """The root functions the SDK mod calls, each built by its own function, in the order they are defined."""
    return [build() for build in ROOT_BUILDERS]
