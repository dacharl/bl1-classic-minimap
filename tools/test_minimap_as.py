"""Run the minimap root functions from a built HUD movie in a tiny AS2 interpreter, against mock clips.

Usage: python -I tools/test_minimap_as.py dist/phase2/HUD_minimap.gfx

Covers the subset of AS2 the root functions use. It checks the logic and the encoding (functions are
decoded from the movie's bytes), not Scaleform itself.
"""
import math
import os
from pathlib import Path
import sys
import struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import as2asm  # noqa: E402
from as2asm import Reg  # noqa: E402
from swfbuild import EXPORT_NAME, top_level  # noqa: E402
from swfdeps import Movie, read_tags  # noqa: E402

PROPS = {0: '_x', 1: '_y', 2: '_xscale', 3: '_yscale', 7: '_visible', 10: '_rotation', 6: '_alpha'}
UNDEF = Ellipsis


class Clip:
    def __init__(self, name, parent=None, depth=0, w=0.0, h=0.0):
        self.name, self.parent, self.depth = name, parent, depth
        self.props = {'_x': 0.0, '_y': 0.0, '_xscale': 100.0, '_yscale': 100.0, '_rotation': 0.0,
                      '_visible': True, '_currentframe': 1}
        self.base_w, self.base_h = w, h
        self.children, self.frame, self.drawn = {}, None, []

    def path(self):
        return '_level0' if self.parent is None else self.parent.path() + '.' + self.name

    def get(self, k):
        if k == '_width':
            return self.base_w * self.props['_xscale'] / 100
        if k == '_height':
            return self.base_h * self.props['_yscale'] / 100
        if k in self.props:
            return self.props[k]
        if k in self.children:
            return self.children[k]
        if k == 'transform':
            return TransformObj(self) if Clip.transform_works else UNDEF
        m = getattr(self, 'as_' + k, None)
        return m if m else UNDEF

    def set(self, k, v):
        # Assigned members (including clip references like _root.mmPlayer) live in props; `children`
        # only holds clips created inside this clip. get() checks props first, as one namespace.
        if k == '_name':  # renaming a clip moves it under the new name in its parent
            p = self.parent
            p.children = {(v if c is self else n): c for n, c in p.children.items()}
            self.name = v
            return
        self.props[k] = v

    def add(self, child):
        self.children[child.name] = child
        child.parent = self
        return child

    # --- MovieClip methods used by the functions ----------------------------------------------
    def dynamic(self):
        return [c for c in self.children.values() if c.depth >= 0]

    def as_getNextHighestDepth(self):
        return max([c.depth for c in self.dynamic()] + [-1]) + 1

    def as_getInstanceAtDepth(self, d):
        for c in self.dynamic():
            if c.depth == d:
                return c
        return UNDEF

    def as_duplicateMovieClip(self, name, depth):
        """Like Flash, the copy takes the source's display state, including _visible."""
        c = Clip(name, None, depth, self.base_w, self.base_h)
        c.props['_visible'] = self.props['_visible']
        return self.parent.add(c)

    transform_works = True  # set False to simulate a runtime without MovieClip.transform

    def as_gotoAndStop(self, frame):
        self.frame = frame
        # maps' frame 1 is the label "none" (blank art); every zone label is a later frame
        self.props['_currentframe'] = 1 if frame == 'none' else 2

    def as_removeMovieClip(self):
        self.parent.children = {k: v for k, v in self.parent.children.items() if v is not self}

    def as_createEmptyMovieClip(self, name, depth):
        return self.add(Clip(name, None, depth))

    attach_works = True  # set False to simulate attachMovie failing under the game's Scaleform

    def as_attachMovie(self, ident, name, depth):
        if not Clip.attach_works:
            return UNDEF
        if ident in ('bl1mm_north', 'bl1mm_objective', 'bl1mm_enemy'):   # edge indicator / threat art
            c = self.add(Clip(name, None, depth))
            c.frame = ident
            return c
        assert ident == EXPORT_NAME, ident
        return self.add(build_map_clip(name, depth))

    def __getattr__(self, k):
        if k.startswith('as_'):
            raise AttributeError(k)
        if k.startswith('as'):
            raise AttributeError(k)
        raise AttributeError(k)

    def beginFill(self, *a):
        self.drawn.append(('beginFill',) + a)


def build_map_clip(name, depth):
    """The bl1mm_map sprite as swfbuild lays it out (Enhanced's sprite 187, PLAN_V09): box art, the
    207.95 x 173.65 window `mask` anchored at its top-left (-103.95, -86.8), maps{themap, landmarks,
    players} at the clip origin."""
    m = Clip(name, None, depth)
    m.add(Clip('box', None, -16381, 263.4, 238.5))
    mask = m.add(Clip('mask', None, -16380, 207.95, 173.65)); mask.props.update(_x=-103.95, _y=-86.8)
    maps = m.add(Clip('maps', None, -16378))
    maps.add(Clip('themap', None, -16383, 779.5, 352.2))   # 3118 x 1408.8 at 400%
    maps.add(Clip('landmarks', None, -16378))
    maps.add(Clip('players', None, -16375))
    return m


def new_root():
    """HUD root as the patched movie has it: the timeline fallback instance, 20000 px off-screen."""
    root = Clip('_root')
    fb = root.add(build_map_clip('mmfallback', -16384 + 600))
    fb.props.update(_x=-20000.0, _y=-20000.0)
    return root


for _m in ('beginFill', 'moveTo', 'lineTo', 'endFill'):
    setattr(Clip, 'as_' + _m, lambda self, *a, _m=_m: self.drawn.append((_m,) + a))


class ASArray(list):
    def get(self, k):
        if k == 'length':
            return len(self)
        if k == 'push':
            return lambda *v: (self.extend(v), len(self))[1]
        if k == 'splice':
            return lambda a, n: [self.pop(int(a)) for _ in range(int(n))]
        i = int(k)
        return self[i] if 0 <= i < len(self) else UNDEF

    def set(self, k, v):
        i = int(k)
        while len(self) <= i:
            self.append(UNDEF)
        self[i] = v


class ASString(str):
    def get(self, k):
        if k == 'length':
            return len(self)
        if k == 'split':
            return lambda sep: ASArray(ASString(x) for x in self.split(sep))
        if k == 'indexOf':
            return lambda s, *a: self.find(s)
        return UNDEF


class Obj:
    def __init__(self, **kw):
        self.d = dict(kw)

    def get(self, k):
        return self.d.get(k, UNDEF)

    def set(self, k, v):
        self.d[k] = v


def make_matrix(a=1.0, b=0.0, c=0.0, d=1.0, tx=0.0, ty=0.0):
    """flash.geom.Matrix: a plain object with a, b, c, d, tx, ty."""
    return Obj(a=num(a), b=num(b), c=num(c), d=num(d), tx=num(tx), ty=num(ty))


class TransformObj:
    """MovieClip.transform (flash.geom.Transform): a fresh object per read; setting .matrix applies the
    whole matrix to the clip (props['_matrix']) and updates _x/_y/_xscale/_yscale from it."""

    def __init__(self, clip):
        self.clip = clip

    def get(self, k):
        if k != 'matrix':
            return UNDEF
        m = self.clip.props.get('_matrix')
        if m is None:
            p = self.clip.props
            return make_matrix(p['_xscale'] / 100.0, 0.0, 0.0, p['_yscale'] / 100.0, p['_x'], p['_y'])
        return make_matrix(*(m.get(x) for x in ('a', 'b', 'c', 'd', 'tx', 'ty')))

    def set(self, k, v):
        if k == 'matrix' and isinstance(v, Obj):
            p = self.clip.props
            p['_matrix'] = v
            p['_x'], p['_y'] = v.get('tx'), v.get('ty')
            p['_xscale'] = math.hypot(v.get('a'), v.get('b')) * 100.0
            p['_yscale'] = math.hypot(v.get('c'), v.get('d')) * 100.0


def wrap(v):
    return ASString(v) if isinstance(v, str) and not isinstance(v, ASString) else v


def num(v):
    if v is UNDEF or v is None:
        return float('nan')
    if isinstance(v, bool):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return float('nan')


def tint_of(clip):
    """RGB a clip is tinted to, from a multiplying colour transform (white -> that colour, dark stays dark,
    alpha untouched); None if untinted. A flat setRGB fill is never accepted (run 15: the turn-in diamond
    lost its ring and centre and its faint glow became a solid square)."""
    assert '_rgb' not in clip.props, 'tints must multiply (setTransform), not flatten (setRGB)'
    ct = clip.props.get('_ct')
    if ct is None:
        return None
    assert (ct['aa'], ct['rb'], ct['gb'], ct['bb'], ct['ab']) == (100, 0, 0, 0, 0), ct
    return sum(int(round(ct[k] * 2.55)) << s for k, s in (('ra', 16), ('ga', 8), ('ba', 0)))


class VM:
    def __init__(self, root):
        self.root = root
        self.funcs = {}
        self.globals = {'Math': Obj(cos=math.cos, sin=math.sin, PI=math.pi, abs=lambda v: abs(num(v)), max=max,
                                    floor=lambda v: float(math.floor(num(v)))),
                        '_root': root, '_level0': root, 'Object': Obj,
                        'Number': lambda v=UNDEF: num(v), 'Array': lambda *a: ASArray(a), 'Color': self.color,
                        'flash': Obj(geom=Obj(Matrix=make_matrix))}

    @staticmethod
    def color(target=UNDEF):
        """new Color(clip): setRGB records props['_rgb'] (a flat fill: every pixel one colour); setTransform
        records the colour transform object's fields as props['_ct']."""
        def set_rgb(v):
            if isinstance(target, Clip):
                target.props['_rgb'] = int(num(v))

        def set_transform(t):
            if isinstance(target, Clip):
                target.props['_ct'] = {k: num(t.get(k)) for k in ('ra', 'ga', 'ba', 'aa', 'rb', 'gb', 'bb', 'ab')}
        return Obj(setRGB=set_rgb, setTransform=set_transform)

    def lookup(self, scope, name):
        if '.' in name:
            parts = name.split('.')
            obj = self.lookup(scope, parts[0])
            for p in parts[1:]:
                obj = obj.get(p) if obj is not UNDEF else UNDEF
            return obj
        if name in scope:
            return scope[name]
        if name in self.funcs:
            return self.funcs[name]
        v = self.root.get(name)
        if v is not UNDEF:
            return v
        return self.globals.get(name, UNDEF)

    def define(self, ir):
        for ins in ir:
            if ins['op'] in (0x9B, 0x8E):
                self.funcs[ins['func']['name']] = ins['func']

    def call(self, name, *args):
        return self.run_func(self.funcs[name], [wrap(a) for a in args])

    def run_func(self, f, args):
        scope, regs = {}, {}
        for i, p in enumerate(f['params']):
            v = args[i] if i < len(args) else UNDEF
            if f['v2']:
                reg, pname = p
                if reg:
                    regs[reg] = v
                else:
                    scope[pname] = v
            else:
                scope[p] = v
        return self.run(f['body'], scope, regs)

    def run(self, ir, scope, regs):
        st = []
        pc = 0
        while pc < len(ir):
            ins = ir[pc]; pc += 1
            n = as2asm.NAMES.get(ins['op'], hex(ins['op']))
            pop = st.pop
            if n == 'Push':
                for v in ins['args']:
                    st.append(regs.get(v.n, UNDEF) if isinstance(v, Reg) else wrap(v))
            elif n == 'Pop':
                pop()
            elif n == 'GetVariable':
                st.append(self.lookup(scope, pop()))
            elif n == 'SetVariable':
                v = pop(); k = pop()
                if k in scope:
                    scope[k] = v
                else:
                    self.root.set(k, v)
            elif n == 'DefineLocal':
                v = pop(); scope[pop()] = v
            elif n == 'GetMember':
                k = pop(); o = pop()
                st.append(o.get(k) if o is not UNDEF and hasattr(o, 'get') else UNDEF)
            elif n == 'SetMember':
                v = pop(); k = pop(); o = pop()
                if o is not UNDEF and hasattr(o, 'set'):    # Flash ignores a member set on undefined
                    o.set(k, v)
            elif n == 'CallMethod':
                m = pop(); o = pop(); k = int(num(pop())); a = [pop() for _ in range(k)]
                f = o.get(m)
                st.append(wrap(f(*a)) if callable(f) else UNDEF)
            elif n == 'CallFunction':
                fn = pop(); k = int(num(pop())); a = [pop() for _ in range(k)]
                f = self.lookup(scope, fn)
                st.append(self.run_func(f, a) if isinstance(f, dict) else wrap(f(*a)))
            elif n == 'NewObject':
                fn = pop(); k = int(num(pop())); a = [pop() for _ in range(k)]
                st.append(self.globals[fn](*a))
            elif n == 'NewMethod':
                m = pop(); o = pop(); k = int(num(pop())); a = [pop() for _ in range(k)]
                f = o.get(m) if o is not UNDEF and hasattr(o, 'get') else UNDEF
                st.append(f(*a) if callable(f) else UNDEF)
            elif n in ('Add2',):
                b = pop(); a = pop()
                st.append(ASString(str(a) + str(int(b) if isinstance(b, float) and b.is_integer() else b))
                          if isinstance(a, str) or isinstance(b, str) else num(a) + num(b))
            elif n in ('Subtract', 'Multiply', 'Divide', 'Modulo'):
                b = num(pop()); a = num(pop())
                if n == 'Subtract':
                    st.append(a - b)
                elif n == 'Multiply':
                    st.append(a * b)
                elif n == 'Divide':
                    st.append(a / b if b else float('inf'))
                else:
                    st.append(math.fmod(a, b) if b else float('nan'))
            elif n == 'Less2':
                b = pop(); a = pop(); st.append(num(a) < num(b))
            elif n == 'Greater':
                b = pop(); a = pop(); st.append(num(a) > num(b))
            elif n == 'Equals2':
                b = pop(); a = pop()
                st.append((a is UNDEF or a is None) and (b is UNDEF or b is None) or a == b)
            elif n == 'Not':
                v = pop()
                st.append(not (v not in (UNDEF, None, 0, '', False) and not (isinstance(v, float) and math.isnan(v))))
            elif n == 'If':
                v = pop()
                if v not in (UNDEF, None, 0, False, ''):
                    pc = ins['target']
            elif n == 'Jump':
                pc = ins['target']
            elif n == 'Return':
                return pop()
            elif n == 'StoreRegister':
                regs[ins['args']] = st[-1]
            elif n == 'TargetPath':
                o = pop(); st.append(ASString(o.path()) if isinstance(o, Clip) else UNDEF)
            elif n == 'SetProperty':
                v = pop(); idx = int(num(pop())); target = pop()
                o = self.lookup(scope, target) if isinstance(target, str) else target
                o.set(PROPS[idx], num(v) if idx != 7 else v)
            elif n == 'GetProperty':
                idx = int(num(pop())); target = pop()
                o = self.lookup(scope, target) if isinstance(target, str) else target
                st.append(o.get(PROPS[idx]))
            else:
                raise NotImplementedError(n)
        return UNDEF


def main(path):
    d = Path(path).read_bytes()
    root = new_root()
    vm = VM(root)
    actions = [as2asm.decode(body) for code, body, _ in top_level(d) if code == 12]
    for ir in actions:
        vm.define(ir)
    need = ['AddLandmark', 'UpdateLandmark', 'SetMapScale', 'InitDLC', 'SetMarkerColor', 'MinimapCreate',
            'MinimapDestroy', 'MinimapClear', 'MinimapRecenter', 'UpdateThreats', 'MinimapPing', 'MinimapDock',
            'MinimapHudShift']
    assert all(n in vm.funcs for n in need), set(need) - set(vm.funcs)

    def close(a, b, tol=1e-6):
        assert abs(a - b) < tol, (a, b)

    # MinimapCreate attaches once and places the clip
    assert vm.call('MinimapCreate', 1000.0, 40.0, 30.0) is True
    m = root.get('map')
    assert isinstance(m, Clip) and m.depth == 9000 and root.get('mmCreateMode') == 'attach'
    close(m.get('_x'), 1000); close(m.get('_y'), 40); close(m.get('_xscale'), 30)
    vm.call('MinimapCreate', 990.0, 50.0, 25.0)
    assert root.get('map') is m, 'second create must reuse the clip'
    close(m.get('_x'), 990); close(m.get('_xscale'), 25)

    # SetMapScale (copied): themap scaled and centred on the maps origin
    vm.call('SetMapScale', 400.0)
    tm = m.get('maps').get('themap')
    close(tm.get('_xscale'), 400); close(tm.get('_x'), -0.5 * tm.get('_width')); close(tm.get('_y'), -0.5 * tm.get('_height'))

    # AddLandmark / UpdateLandmark (copied). The native passes TransformedLocation (0-1 across themap),
    # and UpdateLandmark places the icon at themap._x + u * themap._width (PHASE0 2d).
    def at(u, v):
        return tm.get('_x') + u * tm.get('_width'), tm.get('_y') + v * tm.get('_height')
    p = vm.call('AddLandmark', 'map.maps.players', 0.852, 0.247, 161.19, 'player')
    assert str(p).startswith('_level0.map.maps.player'), p
    player = root.get('mmPlayer')
    assert isinstance(player, Clip) and player.frame == 'player', 'player icon not captured'
    ex, ey = at(0.852, 0.247)
    close(player.get('_x'), ex); close(player.get('_y'), ey); close(player.get('_rotation'), 161.19)
    vm.call('AddLandmark', 'map.maps.landmarks', 0.371, 0.664, 0.0, 'poi')
    assert root.get('mmPlayer') is player, 'non-player landmark must not replace the player'
    vm.call('UpdateLandmark', str(p), 0.6, 0.4, 45.0)
    ex, ey = at(0.6, 0.4)
    close(player.get('_x'), ex); close(player.get('_y'), ey); close(player.get('_rotation'), 45)

    # MinimapRecenter, north-up: player icon lands on the mask centre
    mk, ms = m.get('mask'), m.get('maps')
    cx = mk.get('_x') + mk.get('_width') / 2; cy = mk.get('_y') + mk.get('_height') / 2
    assert vm.call('MinimapRecenter', False, 0) is True
    close(ms.get('_rotation'), 0)
    close(ms.get('_x') + player.get('_x'), cx); close(ms.get('_y') + player.get('_y'), cy)

    # rotating: maps rotated by offset - heading, player still at the centre
    vm.call('MinimapRecenter', True, 90)
    R = 90 - 45
    close(ms.get('_rotation'), R)
    a = math.radians(R)
    sx = ms.get('_x') + (player.get('_x') * math.cos(a) - player.get('_y') * math.sin(a))
    sy = ms.get('_y') + (player.get('_x') * math.sin(a) + player.get('_y') * math.cos(a))
    close(sx, cx); close(sy, cy)

    # UpdateThreats: pool grows, positions follow themap UVs, extras hide
    vm.call('UpdateThreats', '0.25,0.5|0.75,0.1|')
    pool = root.get('mmThreats')
    assert len(pool) == 2
    close(pool[0].get('_x'), tm.get('_x') + 0.25 * tm.get('_width'))
    close(pool[1].get('_y'), tm.get('_y') + 0.1 * tm.get('_height'))
    # Enhanced's threat art (E sprite 128 -> shape 127: red diamond, black outline), not a drawn square, and
    # counter-rotated against the map like Enhanced's CancelOutIconRotation, so it stays a diamond
    assert pool[0].frame == 'bl1mm_enemy' and not pool[0].drawn
    close(pool[0].get('_rotation'), -ms.get('_rotation')); close(pool[1].get('_rotation'), -ms.get('_rotation'))
    vm.call('MinimapRecenter', True, 120)          # the map turns between threat updates
    assert abs(ms.get('_rotation') - R) > 1
    close(pool[0].get('_rotation'), -ms.get('_rotation'))
    vm.call('MinimapRecenter', False, 0)
    close(ms.get('_rotation'), 0); close(pool[1].get('_rotation'), 0)
    vm.call('UpdateThreats', '0.5,0.5|')
    assert len(pool) == 2 and pool[0].get('_visible') is True and pool[1].get('_visible') is False
    vm.call('UpdateThreats', '')
    assert pool[0].get('_visible') is False

    # MinimapClear removes dynamic children only
    vm.call('MinimapClear')
    assert {c.name for c in ms.children.values()} == {'themap', 'landmarks', 'players'}, list(ms.children)
    assert root.get('mmPlayer') is UNDEF and root.get('mmThreats') is UNDEF
    assert vm.call('MinimapRecenter', False, 0) is False, 'no player -> no-op'

    # InitDLC (copied)
    vm.call('InitDLC', 'dlcmap1', 'dlc1_maps.dlcmap_island')
    assert root.get('LoadDLCPackage') == 'dlc1_maps.dlcmap_island' and ms.frame == 'dlcmap1'

    # Python-driven ops (PLAN_DIRECT step A), all through MinimapCmd
    vm.call('MinimapCmd', 'frame~dry')
    assert ms.frame == 'dry'
    vm.call('MinimapCmd', 'scale~300')
    close(tm.get('_xscale'), 300); close(tm.get('_x'), -0.5 * tm.get('_width'))
    vm.call('MinimapCmd', 'tick~0.6~0.4~30~0~0')          # first tick creates the player icon
    pl = root.get('mmPlayer')
    assert isinstance(pl, Clip) and pl.frame == 'player'
    close(pl.get('_x'), tm.get('_x') + 0.6 * tm.get('_width')); close(pl.get('_rotation'), 30)
    close(ms.get('_x') + pl.get('_x'), cx); close(ms.get('_y') + pl.get('_y'), cy)
    vm.call('MinimapCmd', 'tick~0.61~0.42~-90~1~0')       # later ticks move/turn it; rotate on
    assert root.get('mmPlayer') is pl
    close(pl.get('_x'), tm.get('_x') + 0.61 * tm.get('_width')); close(pl.get('_rotation'), -90)
    close(ms.get('_rotation'), 90)
    a = math.radians(90)
    close(ms.get('_x') + pl.get('_x') * math.cos(a) - pl.get('_y') * math.sin(a), cx)
    close(ms.get('_y') + pl.get('_x') * math.sin(a) + pl.get('_y') * math.cos(a), cy)
    before = len(ms.children)
    vm.call('MinimapCmd', 'add~map.maps.landmarks~0.25~0.75~12~poi')
    added = [c for c in ms.children.values() if c.frame == 'poi' and c.get('_rotation') == 12]
    assert len(ms.children) == before + 1 and added
    close(added[0].get('_x'), tm.get('_x') + 0.25 * tm.get('_width'))
    close(added[0].get('_y'), tm.get('_y') + 0.75 * tm.get('_height'))
    # Run 23 (PHASE3 3an): like Enhanced's CancelOutIconRotation (every icon in iconPathArray, not only threats),
    # every map icon stays upright while the map turns; the player icon keeps its heading
    vm.call('MinimapCmd', 'tick~0.61~0.42~-60~1~0')
    close(ms.get('_rotation'), 60)
    close(added[0].get('_rotation'), -60); close(pl.get('_rotation'), -60)
    vm.call('MinimapCmd', 'tick~0.61~0.42~-60~0~0')       # north-up again: icons straight
    close(ms.get('_rotation'), 0); close(added[0].get('_rotation'), 0)
    assert tint_of(added[0]) is None, 'untinted add must not touch the colour'
    vm.call('MinimapCmd', 'add~map.maps.landmarks~0.3~0.3~0~objective~16761888')     # 0xFFC420 tint
    tinted = [c for c in ms.children.values() if c.frame == 'objective' and c.props.get('_ct')]
    assert len(tinted) == 1 and tint_of(tinted[0]) == 0xFFC420, 'optional 7th field tints the new icon'
    ct = tinted[0].props['_ct']
    close(ct['ra'], 100); close(ct['ga'], 0xC4 / 2.55); close(ct['ba'], 0x20 / 2.55)   # multiplies: dark stays dark
    vm.call('MinimapCmd', 'bogus~1')
    assert root.get('mmBadCmd') == 'bogus~1'

    # Source clips (run 9 stuck diamond/arrow): clear hides maps.landmarks/players; every icon created
    # afterwards is shown explicitly, although duplicateMovieClip copies the hidden state
    vm.call('MinimapCmd', 'clear')
    src_l, src_p = ms.get('landmarks'), ms.get('players')
    assert src_l.get('_visible') is False and src_p.get('_visible') is False, 'icon templates must be hidden'
    vm.call('MinimapCmd', 'add~map.maps.landmarks~0.4~0.4~0~poi')
    vm.call('MinimapCmd', 'tick~0.5~0.5~10~0~0')
    shown = [c for c in ms.dynamic() if c.frame in ('poi', 'player')]
    assert len(shown) == 2 and all(c.get('_visible') is True for c in shown), [(c.frame, c.props) for c in shown]
    assert src_l.get('_visible') is False and src_p.get('_visible') is False

    # MinimapDock: full matrix through transform.matrix (shear kept), read back
    vm.call('MinimapCmd', 'dock~0.187~0.0131~0~0.1876~1070.5~45.2')
    assert root.get('mmDockMode') == 'matrix', root.get('mmDockMode')
    mt = m.props['_matrix']
    close(mt.get('b'), 0.0131); close(mt.get('a'), 0.187); close(mt.get('tx'), 1070.5); close(root.get('mmDockB'), 0.0131)
    # runtime without MovieClip.transform: position + scale, no shear, reported as "plain"
    Clip.transform_works = False
    try:
        vm.call('MinimapCmd', 'dock~0.2~0.014~0~0.2~900~60')
        assert root.get('mmDockMode') == 'plain'
        close(m.get('_x'), 900); close(m.get('_y'), 60); close(m.get('_xscale'), 20); close(m.get('_yscale'), 20)
    finally:
        Clip.transform_works = True

    # MinimapHudShift: record the authored p1 column once, apply Enhanced's placements, restore exactly
    p1 = root.add(Clip('p1')); p1.props.update(_x=216.1, _y=30.4)
    authored = {'echo': (791.5, 37.1), 'quest': (545.0, 171.1)}
    authored.update({'check%d' % i: (747.2, 92.4 + 19.7 * (i - 1)) for i in range(1, 6)})
    for n, (x, y) in authored.items():
        c = p1.add(Clip(n)); c.props.update(_x=x, _y=y, _xscale=100.04, _yscale=100.0)
    hud = 'hud~%d~610~13.1~577~129.1~795.9~59.4~16.4~92.02~92'
    vm.call('MinimapCmd', hud % 2)                       # record only
    close(root.get('mmEchoX0'), 791.5); close(p1.get('echo').get('_x'), 791.5)
    vm.call('MinimapCmd', hud % 1)
    close(p1.get('echo').get('_x'), 610); close(p1.get('echo').get('_y'), 13.1)
    close(p1.get('quest').get('_x'), 577); close(p1.get('check3').get('_y'), 59.4 + 2 * 16.4)
    close(p1.get('check5').get('_xscale'), 92.02); close(p1.get('echo').get('_xscale'), 100.04)
    # Run 25 (Deck): the game re-plays p1's first frame, which puts the column back at its authored places while
    # the shift is on (F7: hud_shifted True, echo_x 791.45). Each tick re-applies the shift and counts it.
    vm.call('MinimapCmd', 'tick~0.5~0.5~0~0~0')
    assert root.get('mmHudFixes') in (None, UNDEF, 0), 'no fix while the column is where the shift put it'
    for n, (x, y) in authored.items():
        c = p1.get(n); c.props.update(_x=x, _y=y, _xscale=100.04, _yscale=100.0)
    vm.call('MinimapCmd', 'tick~0.5~0.5~0~0~0')
    close(p1.get('echo').get('_x'), 610); close(p1.get('quest').get('_y'), 129.1); close(p1.get('check5').get('_xscale'), 92.02)
    vm.call('MinimapCmd', 'tick~0.5~0.5~0~0~0')
    assert root.get('mmHudFixes') == 1, root.get('mmHudFixes')
    close(root.get('mmEchoX0'), 791.5)
    # The user saw a brief flicker behind the map even with the 1 s re-dock: the map clip also runs the check on
    # every movie frame (onEnterFrame, before the frame is drawn), so a reset doesn't wait for the mod's tick.
    keep = m.get('onEnterFrame')
    assert keep is vm.funcs['MinimapHudKeep'], 'the map clip checks the column every frame'
    for n, (x, y) in authored.items():
        c = p1.get(n); c.props.update(_x=x, _y=y, _xscale=100.04, _yscale=100.0)
    vm.run_func(keep, [])
    close(p1.get('echo').get('_x'), 610); assert root.get('mmHudFixes') == 2
    for _ in range(3):                                   # repeated toggles don't drift
        vm.call('MinimapCmd', hud % 0); vm.call('MinimapCmd', hud % 1)
    vm.call('MinimapCmd', hud % 0)
    for n, (x, y) in authored.items():
        c = p1.get(n)
        close(c.get('_x'), x); close(c.get('_y'), y); close(c.get('_xscale'), 100.04); close(c.get('_yscale'), 100.0)
    close(root.get('mmEchoX0'), 791.5), 'originals must not be re-recorded from shifted values'
    assert root.get('mmHudMode') == 0
    vm.call('MinimapCmd', 'tick~0.5~0.5~0~0~0')
    close(p1.get('echo').get('_x'), 791.5); assert root.get('mmHudFixes') == 2, 'restored: ticks leave it alone'
    root.children.pop('p1')

    # PLAN_V08 movie structure: Enhanced turnin/newmission frames appended to the landmark sprite; the
    # north and objective art exported for the edge indicators
    mv = Movie(data=d)
    assert {1306: 'bl1mm_north', 1050: 'bl1mm_objective', 1200: 'bl1mm_map', 1311: 'bl1mm_enemy'}.items() \
        <= mv.exports.items()
    # threat art: a one-frame wrapper around shape 1310 (Enhanced's shape 127, or the original art's diamond)
    enemy = [(c, b) for c, b in read_tags(mv.defs[1311][1], 4, len(mv.defs[1311][1])) if c in (26, 70)]
    assert len(enemy) == 1 and struct.unpack_from('<H', enemy[0][1], 3)[0] == 1310 and mv.defs[1310][0] in (2, 32)
    labels = [b.split(b'\0')[0].decode() for c, b in read_tags(mv.defs[1066][1], 4, len(mv.defs[1066][1])) if c == 43]
    assert labels[-3:] == ['questionmark', 'turnin', 'newmission'], labels
    # PLAN_V09: bl1mm_map is Enhanced's minimap clip layout: box art at depth 3, the window as a clip layer
    # named mask at depth 4 masking through depth 6, maps at depth 6
    places = [b for c, b in read_tags(mv.defs[1200][1], 4, len(mv.defs[1200][1])) if c == 26]
    by_depth = {struct.unpack_from('<H', b, 1)[0]: b for b in places}
    assert sorted(by_depth) == [3, 4, 6], sorted(by_depth)
    assert struct.unpack_from('<H', by_depth[3], 3)[0] == 1307                       # Enhanced box (E shape 81)
    m4 = by_depth[4]
    assert m4[0] & 0x40 and m4.endswith(b'mask\0' + struct.pack('<H', 6)), m4.hex()  # clip layer to depth 6
    assert by_depth[6].endswith(b'maps\0') and struct.unpack_from('<H', by_depth[6], 3)[0] == 1132

    # icon scale (Enhanced draws icons at its map clip's 0.7; ours are scaled up to match)
    vm.call('MinimapCmd', 'clear')
    vm.call('MinimapCmd', 'recenter~0~0')
    ms._rotation = 0
    ms.props['_rotation'] = 0.0
    vm.call('MinimapCmd', 'iconscale~373')
    vm.call('MinimapCmd', 'add~map.maps.landmarks~0.5~0.5~0~newmission')
    vm.call('MinimapCmd', 'tick~0.5~0.5~0~0~0')
    nm = [c for c in ms.dynamic() if c.frame == 'newmission'][0]
    close(nm.get('_xscale'), 373); close(root.get('mmPlayer').get('_xscale'), 373)
    vm.call('MinimapCmd', 'threats~0.5,0.5')
    close(root.get('mmThreats')[0].get('_xscale'), 373)
    # edge indicators: north on the top edge (north-up), objectives only when outside the window
    north = m.get('mmNorth')
    mk = m.get('mask')
    cx, cy = mk.get('_x') + mk.get('_width') / 2, mk.get('_y') + mk.get('_height') / 2
    EX, EY = 110.0, 92.0                               # Enhanced's edge path (E sprites 182/186), on the box border
    assert isinstance(north, Clip) and north.frame == 'bl1mm_north'
    close(north.get('_x'), cx, 1e-6); close(north.get('_y'), cy - EY, 1e-6)
    vm.call('MinimapCmd', 'add~map.maps.landmarks~0.52~0.5~0~objective')          # just right of the player
    vm.call('MinimapCmd', 'add~map.maps.landmarks~2.5~0.5~0~objective~16761888')  # far east, off the window
    assert len(root.get('mmObjectives')) == 2
    vm.call('MinimapCmd', 'tick~0.5~0.5~0~0~0')
    e0, e1 = m.get('mmEdge0'), m.get('mmEdge1')
    assert e0.get('_visible') is False, 'an objective inside the window gets no edge indicator'
    assert e1.get('_visible') is True and e1.frame == 'bl1mm_objective'
    close(e1.get('_x'), cx + EX, 1e-6); close(e1.get('_y'), cy, 1e-3)
    close(e1.get('_xscale'), 373 * 0.55, 1e-6); assert tint_of(e1) == 16761888
    # run 12 "double waypoint": while the edge diamond shows, the objective's own icon (partly clipped at the
    # window border) is hidden; the inside one keeps its icon. At the switch point both sit at the same
    # spot, so one marker slides onto the edge.
    o_in, o_out = root.get('mmObjectives')[0], root.get('mmObjectives')[1]
    assert o_out.get('_visible') is False and o_in.get('_visible') is True
    o_out.props['_x'] = o_in.get('_x')                 # the far objective comes back inside the window
    vm.call('MinimapCmd', 'tick~0.5~0.5~0~0~0')
    assert e1.get('_visible') is False and o_out.get('_visible') is True
    o_out.props['_x'] = tm.get('_x') + 2.5 * tm.get('_width')
    vm.call('MinimapCmd', 'tick~0.5~0.5~0~0~0')
    assert e1.get('_visible') is True and o_out.get('_visible') is False
    # Run 13: hand over before the objective is partly clipped by the actual window.
    # Use the measured objective art extent (24.8 units at Icon size 100%).
    vm.call('MinimapCmd', 'iconscale~100')
    o_out.base_w = o_out.base_h = 24.8
    o_out.props['_xscale'] = o_out.props['_yscale'] = 100
    o_out.props.update(_x=0, _y=-80)
    vm.call('MinimapCmd', 'tick~0.5~0.5~0~0~0')
    assert e1.get('_visible') is True and o_out.get('_visible') is False, 'partial icon must become an edge diamond'
    close(e1.get('_y'), cy - EY, 1e-6)
    for dx, dy, size, outside in ((0, -70, 100, False), (95, 0, 100, True),
                                  (90, 0, 100, False), (0, -70, 150, True),
                                  (0, 80, 100, True), (-95, 0, 100, True)):
        o_out.props.update(_x=dx, _y=dy, _xscale=size, _yscale=size)
        vm.call('MinimapCmd', 'tick~0.5~0.5~0~0~0')
        assert e1.get('_visible') is outside and o_out.get('_visible') is not outside, (dx, dy, size)
    # Run 14 "wobble": classic's objective art animates (sprite 1050's ring, shape 1049, scales 1.0 -> 2.2 over
    # 12 frames), so the icon's live _width pulses between ~24.8 and ~48 units. The handoff must use the icon's
    # static size (its scale), or it flips with the animation while nothing moves.
    o_out.props.update(_x=0, _y=-70, _xscale=100, _yscale=100)
    for pulse in (24.8, 48.0, 30.0, 48.0, 24.8):
        o_out.base_w = o_out.base_h = pulse
        vm.call('MinimapCmd', 'tick~0.5~0.5~0~0~0')
        assert e1.get('_visible') is False and o_out.get('_visible') is True, pulse
    # rotating the map moves north along the edge (Enhanced northMC.gotoAndStop(currentRot))
    vm.call('MinimapCmd', 'tick~0.5~0.5~-90~1~0')            # heading east -> maps rotated +90
    close(ms.get('_rotation'), 90)
    close(north.get('_x'), cx + EX, 1e-6); close(north.get('_y'), cy, 1e-6)
    vm.call('MinimapCmd', 'clear')
    assert root.get('mmObjectives') is UNDEF and root.get('mmEdges') is UNDEF and m.get('mmEdge1') is UNDEF
    vm.call('MinimapCmd', 'tick~0.5~0.5~0~0~0')

    # MinimapDestroy
    vm.call('MinimapDestroy')
    assert root.get('map') is UNDEF
    assert isinstance(root.get('mmfallback'), Clip), 'attach path must not consume the fallback'

    # MinimapPing: side effect the mod reads back (classic Invoke returns nothing usable)
    vm.call('MinimapPing', 'pong7')
    assert root.get('mmPing') == 'pong7'

    # attachMovie failing: MinimapCreate falls back to the timeline instance, renamed to `map`
    Clip.attach_works = False
    try:
        vm.call('MinimapCreate', 1000.0, 40.0, 30.0)
        m = root.get('map')
        assert isinstance(m, Clip) and m.name == 'map' and root.get('mmfallback') is UNDEF
        assert root.get('mmCreateMode') == 'fallback'
        close(m.get('_x'), 1000); assert m.get('_visible') is True
        vm.call('SetMapScale', 300.0)
        p = vm.call('AddLandmark', 'map.maps.players', 0.5, 0.5, 0.0, 'player')
        assert str(p).startswith('_level0.map.maps.player') and root.get('mmPlayer') is not UNDEF
        assert vm.call('MinimapRecenter', False, 0) is True
        vm.call('MinimapDestroy')
        fb = root.get('mmfallback')
        assert root.get('map') is UNDEF and isinstance(fb, Clip), 'fallback must get its name back'
        assert fb.get('_visible') is False and fb.get('_x') == -20000
    finally:
        Clip.attach_works = True
    print('all minimap AS checks passed (%d functions, attach and fallback paths)' % len(need))


if __name__ == '__main__':
    main(sys.argv[1])
