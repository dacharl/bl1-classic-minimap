"""Offline integration test: the real classic_minimap mod + the real built HUD movie's ActionScript.

Usage: python -I tools/test_minimap_mod.py dist/phase2/HUD_minimap.gfx

unrealsdk / mods_base are stubbed. movie.Invoke runs root functions in tools/test_minimap_as.py's AS2
interpreter, decoded from the built movie. The WillowGFxHelperMap natives are emulated with the behaviour
measured in game (PHASE0 2d) and decompiled (ENHANCED_NATIVE.md): Init builds MapObjectData records with
the real field names, InitMapFrame picks the zone frame. The expected Transform/CoordScale are the helper's
own values logged in game for the Arid anchor; the mod must reproduce them from the anchor's fields.
"""
import json
import math
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import as2asm  # noqa: E402
import test_minimap_as as asvm  # noqa: E402
from swfbuild import top_level  # noqa: E402

UNDEF = Ellipsis


# ---- stubs for unrealsdk / mods_base -----------------------------------------------------------
class Struct(types.SimpleNamespace):
    pass


HOOKS, KEYBINDS, CONSTRUCTED = {}, {}, []
OBJECTS = {}            # path -> object, for find_object
PACKAGES = {}           # package name -> {path: object} added by load_package
LOADED = []


def make_struct(name, **kw):
    return Struct(_type=name, **kw)


def find_object(cls, path):
    if path not in OBJECTS:
        raise ValueError('object not found: %s' % path)
    return OBJECTS[path]


def load_package(name, flags=0):
    LOADED.append(name)
    if name not in PACKAGES:
        raise ValueError('package not found: %s' % name)
    OBJECTS.update(PACKAGES[name])
    return Struct(name=name)


KEEP_ALIVE = 0x4000        # mods_base WillowObjectFlags.KEEP_ALIVE


class WeakPointer:
    """unrealsdk.unreal.WeakPointer stand-in: None once the target is destroyed (fake GC)."""

    def __init__(self, obj=None):
        self.obj = obj

    def __call__(self):
        return None if self.obj is None or getattr(self.obj, 'destroyed', False) else self.obj


TRACKERS = []         # find_all("MissionTracker") results
GLOBALS = []          # find_all("WillowGlobals") results (class default first, like the engine)


def find_all(cls, exact=True):
    if cls == 'WillowGlobals':
        return list(GLOBALS)
    assert cls == 'MissionTracker', cls
    return list(TRACKERS)


class FakeGlobals:
    def __init__(self, name, ios):
        self.name, self.ClientInteractiveObjects = name, ios

    def __str__(self):
        return "WillowGlobals'Transient.%s'" % self.name


class Giver:
    """WillowInteractiveObject with MissionDirectives. GetEligibleMissions / GetRedeemableMissions behave like
    pyunrealsdk bound functions with an out parameter: the out argument is a required positional argument
    (run 12: "GetRedeemableMissions() missing 1 required positional argument: 'RedeemableMissions'"), and
    the call returns (ReturnValue, out array)."""

    def __init__(self, name, loc, eligible=0, redeemable=0, directives=1):
        self.name, self.Location = name, loc
        self.eligible, self.redeemable = eligible, redeemable
        self.MissionDirectives = [object()] * directives
        self.fail = False

    def GetEligibleMissions(self, WPC, EligibleMissions):
        if self.fail:
            raise RuntimeError('script call failed')
        return (self.eligible, ['M'] * self.eligible)

    def GetRedeemableMissions(self, WPC, RedeemableMissions):
        return (self.redeemable, ['M'] * self.redeemable)

    def __str__(self):
        return "WillowInteractiveObject'%s'" % self.name


def install_stubs(helper_factory, get_pc):
    unrealsdk = types.ModuleType('unrealsdk')
    unrealsdk.make_struct = make_struct
    unrealsdk.find_object = find_object
    unrealsdk.find_all = find_all
    unrealsdk.load_package = load_package

    def construct_object(cls, outer, name='None', flags=0, template_obj=None):
        CONSTRUCTED.append((cls, outer))
        obj = helper_factory(outer)
        obj.ObjectFlags = flags
        return obj

    unrealsdk.construct_object = construct_object
    hooks = types.ModuleType('unrealsdk.hooks')
    hooks.Type = types.SimpleNamespace(PRE='PRE', POST='POST', POST_UNCONDITIONAL='POSTU')
    unrealsdk.hooks = hooks
    unreal = types.ModuleType('unrealsdk.unreal')
    unreal.WeakPointer = WeakPointer
    unrealsdk.unreal = unreal
    mb = types.ModuleType('mods_base')
    mb.ObjectFlags = types.SimpleNamespace(KEEP_ALIVE=KEEP_ALIVE)
    import tempfile
    from pathlib import Path
    mb.SETTINGS_DIR = Path(tempfile.mkdtemp(prefix='mm_settings_'))

    class Opt:
        def __init__(self, identifier, value=None, *a, **kw):
            self.identifier, self.value, self.args, self.kw = identifier, value, a, kw
            self.on_change_while_enabled = kw.get('on_change_while_enabled')
            for k, v in kw.items():
                setattr(self, k, v)

    for n in ('BoolOption', 'SliderOption', 'SpinnerOption', 'ButtonOption'):
        setattr(mb, n, type(n, (Opt,), {}))

    def hook(name, typ='PRE', **kw):
        def deco(f):
            HOOKS[name] = f
            return f
        return deco

    def keybind(name, key=None, **kw):
        def deco(f):
            KEYBINDS[name] = f
            return f
        return deco

    mb.hook, mb.keybind, mb.get_pc = hook, keybind, get_pc
    mb.build_mod = lambda **kw: types.SimpleNamespace(**kw)
    sys.modules.update({'unrealsdk': unrealsdk, 'unrealsdk.hooks': hooks, 'unrealsdk.unreal': unreal,
                        'mods_base': mb})


# ---- game-side fakes -----------------------------------------------------------------------------
TRANSFORM = Struct(XPlane=Struct(X=1.6779256839072332e-05, Y=-2.5702727057819175e-08, Z=0.0, W=0.0),
                   YPlane=Struct(X=5.14782776406264e-08, Y=8.37775951367803e-06, Z=0.0, W=0.0),
                   ZPlane=Struct(X=0.0, Y=0.0, Z=1.0, W=0.0),
                   WPlane=Struct(X=0.4768569767475128, Y=0.0831480547785759, Z=-15184.999, W=1.0))
COORD_SCALE = Struct(X=1.0, Y=1.1066155433654785)


def _column(echo, quest, check):
    col = {'echo': echo, 'quest': quest}
    col.update({'check%d' % i: (check[0], check[1] + 19.7 * (i - 1)) for i in range(1, 6)})
    return col


# classic HUD root places p1 per layout (16_9_end: sprite 706; 4_3_end: sprite 722 at _xscale 132)
P1_LAYOUTS = {
    '16:9': dict(x=216.1, y=30.4, sx=100.0, column=_column((791.5, 37.1), (545.0, 171.1), (747.2, 92.4))),
    '4:3': dict(x=80.5, y=30.4, sx=132.0, column=_column((655.5, 37.1), (427.9, 180.3), (626.2, 101.4))),
}
# Enhanced's p1-space minimap placement and column (E_HUD sprites 933 / 949), the expected targets
ENH = {'16:9': dict(map=(0.698, 0.049, 0.0, 0.700, 919.4, 73.4), echo=(610.0, 13.1), quest=(577.0, 129.1),
                    check=(795.9, 59.4)),
       '4:3': dict(map=(0.698, 0.049, 0.0, 0.700, 708.4, 99.4), echo=(615.5, 26.1), quest=(377.9, 180.1),
                   check=(596.8, 109.0))}

STOCK_INFO = Struct(name="GFxMovieInfo'GfxHUD.FlashMovie.HUD'")
MINIMAP_INFO = Struct(name="GFxMovieInfo'GfxHUD_Minimap.FlashMovie.HUD'")
TEMPLATE = Struct(name='hud_instance', MovieInfo=STOCK_INFO)


def native_tr(loc):
    m = TRANSFORM
    u = loc.X * m.XPlane.X + loc.Y * m.YPlane.X + loc.Z * m.ZPlane.X + m.WPlane.X
    v = loc.X * m.XPlane.Y + loc.Y * m.YPlane.Y + loc.Z * m.ZPlane.Y + m.WPlane.Y
    return (v + 0.5) * COORD_SCALE.X, (0.5 - u) * COORD_SCALE.Y


def vec(x, y, z=0.0):
    return Struct(X=x, Y=y, Z=z)


class Actor:
    def __init__(self, loc, yaw=0, enemy=False, alive=True):
        self.Location, self.yaw, self.enemy, self.alive = loc, yaw, enemy, alive
        self.NextPawn, self.Controller = None, None

    @property
    def Rotation(self):
        return Struct(Pitch=0, Yaw=self.yaw, Roll=0)

    def IsAliveAndWell(self):
        return self.alive

    def IsEnemy(self, other):
        return other.enemy


class Movie:
    """WillowHUDGFxMovie stand-in: Invoke/GetVariableNumber/SetVariableBool over the AS2 interpreter."""

    def __init__(self, gfx, patched=True, info=None):
        # A HUD movie spawned from the hud_instance template: MovieInfo is copied from the template.
        self.MovieInfo = info if info is not None else (MINIMAP_INFO if patched else STOCK_INFO)
        self.root = asvm.new_root() if patched else asvm.Clip('_root')   # patched movie has mmfallback
        self.vm = asvm.VM(self.root)
        if patched:
            for code, body, _ in top_level(gfx):
                if code == 12:
                    self.vm.define(as2asm.decode(body))
        self.add_p1(P1_LAYOUTS['16:9'])
        self.invokes = []
        self.visible_sets = []      # every map._visible write, to catch a rebuild hiding the map

    def add_p1(self, lay):
        """The stock p1 HUD clip as the layout sprite places it (classic 706 = 16:9, 722 = 4:3), with the
        right-hand column the mod moves aside: echo, quest, check1..5 (authored placements)."""
        p1 = asvm.Clip('p1')
        p1.props.update(_x=lay['x'], _y=lay['y'], _xscale=lay['sx'])
        self.root.add(p1)
        p1.add(asvm.Clip('bearing'))
        for n, (x, y) in lay['column'].items():
            c = p1.add(asvm.Clip(n)); c.props.update(_x=x, _y=y, _xscale=100.04, _yscale=100.0)
        return p1

    def Invoke(self, method, args):
        # Calling GFxMovie.Invoke from Python crashed the game: classic leaves its ASValue return (with
        # an FString) uninitialised and pyunrealsdk read it (PHASE3 3e). The mod must never call it.
        raise AssertionError('mod called GFxMovie.Invoke(%r)' % method)

    def SingleArgInvokeS(self, command, arg):
        """WillowGFxMovie.SingleArgInvokeS: native, calls the AS function with one string, returns nothing."""
        self.invokes.append((command, arg))
        if command in self.vm.funcs:
            self.vm.call(command, arg)

    def GetVariableNumber(self, path):
        v = self.vm.lookup({}, path)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else float('inf')

    def GetVariableString(self, path):
        v = self.vm.lookup({}, path)
        return '' if v is UNDEF or v is None else str(v)

    def GetVariableBool(self, path):
        return bool(self.vm.lookup({}, path))

    def SetVariableBool(self, path, v):
        if path == 'map._visible':
            self.visible_sets.append(v)
        obj, member = path.rsplit('.', 1)
        o = self.vm.lookup({}, obj)
        if o is not UNDEF:
            o.set(member, v)


class HUD:
    """WillowHUD stand-in: GetHUDMovie() and bShowHUD."""

    def __init__(self, movie, shown=True):
        self.movie, self.bShowHUD = movie, shown

    def GetHUDMovie(self):
        return self.movie


class MapObject(Struct):
    pass


class FakeField:
    def __init__(self, name, kind):
        self.Name, self.Class = name, types.SimpleNamespace(Name=kind)


class FakeAnchor:
    """LevelLandmarkAnchor_0 of arid_p, with the field values logged in game (classic_minimap_anchors.jsonl)
    and a reflectable class for the field record."""
    Location = Struct(X=-28388.716796875, Y=-10011.951171875, Z=15184.9990234375)
    Rotation = Struct(Pitch=0, Yaw=32, Roll=0)
    DrawScale = 1.0
    DrawScale3D = Struct(X=58.2003059387207, Y=233.1310272216797, Z=160.99807739257812)
    TextureSizeX, TextureSizeY = 1024, 512
    MapFrame, DLCMap = 'Arid', None
    values = {'Location': 'Vector(-28388.7, -10011.9, 15185.0)', 'DrawScale': 1.0, 'TextureSizeX': 1024,
              'TextureSizeY': 512, 'bHidden': True, 'Tag': 'LevelLandmarkAnchor'}
    Outer = "Level'arid_p.TheWorld:PersistentLevel'"
    Class = types.SimpleNamespace(_fields=lambda: [
        FakeField('Location', 'StructProperty'), FakeField('DrawScale', 'FloatProperty'),
        FakeField('TextureSizeX', 'IntProperty'), FakeField('TextureSizeY', 'IntProperty'),
        FakeField('bHidden', 'BoolProperty'), FakeField('Tag', 'NameProperty'),
        FakeField('Components', 'ArrayProperty'), FakeField('Tick', 'Function')])

    def _get_field(self, f):
        return self.values[f.Name]

    def __str__(self):
        return "LevelLandmarkAnchor'arid_p.TheWorld:PersistentLevel.LevelLandmarkAnchor_0'"


WORLD = types.SimpleNamespace(anchor_loaded=True, zone_frame='arid',
                              interactive=[(vec(-13000.0, 31000.0, 200.0), 'shop')])


def radar_icon(loc=None, active=False, icon_type=2):
    """WillowRadarManager.RemoteDynamicRadarIconData (IconType 2 = RadarIconType_Threat)."""
    return Struct(Location=loc or vec(0.0, 0.0, 0.0), IconType=icon_type, FadeStartTime=0.0, bActive=active)


class Helper:
    """Emulates the classic native WillowGFxHelperMap as observed in game (PHASE0, steam-deck research)."""

    def __init__(self, movie, pc, landmarks):
        self.movie, self.pc, self.landmarks = movie, pc, landmarks
        self.MapObjects = []
        self.Anchor = None
        self.Transform = Struct(XPlane=Struct(X=0.0, Y=0.0, Z=0.0, W=0.0), YPlane=Struct(X=0.0, Y=0.0, Z=0.0, W=0.0),
                                ZPlane=Struct(X=0.0, Y=0.0, Z=0.0, W=0.0), WPlane=Struct(X=0.0, Y=0.0, Z=0.0, W=0.0))
        self.CoordScale = Struct(X=1.0, Y=0.0)
        self.AnchorSize = Struct(X=1024.0, Y=512.0)
        self.ClipSize = Struct(X=0.0, Y=0.0)
        self.ViewSize = Struct(X=0.0, Y=0.0)
        self.calls = []

    @staticmethod
    def record(clip, frame, **kw):
        """MapObjectData with the classic field names (stride 0x54: Player, Landmark,
        ClientInteractiveObject, WPRI, bWaypoint, CustomObjectLoc, ...)."""
        fields = dict(Player=None, Landmark=None, ClientInteractiveObject=None, WPRI=None, bWaypoint=False,
                      CustomObjectLoc=vec(0.0, 0.0, 0.0), bIsDirty=False, TransformedLocation=vec(0.0, 0.0),
                      Angle=0.0, AS_IconClipPath=clip, AS_IconClipFrame=frame, AS_IconPath='')
        fields.update(kw)
        return MapObject(**fields)

    def Init(self, pc):
        """Script FindLandmarks (transitions, Anchor) + native FindObjects (interactive objects, objective
        slots with bWaypoint and the slot location copied into CustomObjectLoc) + FindPlayers. The anchor
        exists only once its level streamed in."""
        self.calls.append('Init')
        self.Anchor = FakeAnchor() if WORLD.anchor_loaded else None
        lm = 'map.maps.landmarks'
        for loc, frame in self.landmarks:
            self.MapObjects.append(self.record(lm, frame, Landmark=Actor(loc)))
        for loc, frame in WORLD.interactive:
            self.MapObjects.append(self.record(lm, frame, ClientInteractiveObject=Actor(loc)))
        for slot in pc.WorldInfo.GRI.ActiveWaypointData:
            l = slot.WaypointLocation
            if l.X or l.Y or l.Z:
                self.MapObjects.append(self.record(lm, 'objective', bWaypoint=True, CustomObjectLoc=vec(l.X, l.Y, l.Z)))
        self.MapObjects.append(self.record(lm, 'poi'))                       # zero custom vector: skipped
        self.MapObjects.append(self.record('map.maps.players', 'player', Player=pc))
        self.MapObjects.append(self.record('map.maps.players', 'buddy1', WPRI=object()))   # co-op: moving

    def InitMapFrame(self, movie):
        """No anchor -> frame stays "none"; otherwise map.maps.gotoAndStop(<zone label>)."""
        self.calls.append('InitMapFrame')
        maps = movie.vm.lookup({}, 'map.maps')
        assert maps is not UNDEF, 'InitMapFrame before MinimapCreate'
        maps.as_gotoAndStop(WORLD.zone_frame if self.Anchor is not None else 'none')
        return True

    def InitMapFrameVars(self, movie):
        raise AssertionError('v0.6 computes ClipSize/CoordScale itself; InitMapFrameVars must not be called')

    def UpdateObjects(self, static):
        raise AssertionError('v0.6 projects in Python; UpdateObjects must not be called')


def main(gfx_path):
    gfx = open(gfx_path, 'rb').read()
    clock = [1000.0]
    world = types.SimpleNamespace()
    pc = types.SimpleNamespace()
    pc.Pawn = Actor(vec(-11998.6, 32060.8, 126.4), yaw=29344)          # the logged Fyrestone pawn
    pc.Pawn.enemy = False
    pc.loading_movie = False
    pc.IsLoadingMoviePlaying = lambda: pc.loading_movie
    pc.bCinematicMode = False
    pc.bStatusMenuOpen = False
    enemy = Actor(vec(-11000.0, 32500.0, 120.0), enemy=True)
    far = Actor(vec(20000.0, -40000.0, 0.0), enemy=True)
    dead = Actor(vec(-11900.0, 32000.0, 0.0), enemy=True, alive=False)
    pc.Pawn.NextPawn, enemy.NextPawn, far.NextPawn = enemy, far, dead
    world.PawnList = pc.Pawn
    world.PersistentLevel = "Level'Loader.TheWorld:PersistentLevel'"
    # WillowGameReplicationInfo.ActiveWaypointData[8]: the live objective slots the native rereads
    slots = [Struct(WaypointLocation=vec(0.0, 0.0, 0.0), WaypointRadius=0.0) for _ in range(8)]
    slots[0].WaypointLocation = vec(-12000.0, 33000.0, 100.0)
    # GRI.RadarMgr.RemoteDynamicIcons[18]: what the compass radar (and Enhanced's UpdateThreats) reads
    radar = types.SimpleNamespace(RemoteDynamicIcons=[radar_icon() for _ in range(18)], NumberOfDynamicIcons=0)
    world.GRI = types.SimpleNamespace(ActiveWaypointData=slots, RadarMgr=radar)
    arid = types.SimpleNamespace(bIsVisible=True, LoadedLevel='Level arid_p.TheWorld:PersistentLevel')
    world.StreamingLevels = [arid]
    pc.WorldInfo = world
    mission_a = types.SimpleNamespace(TargetWaypointDefinition='WaypointDef A', TurnInWaypointDefinition='TurnIn A')
    mission_b = types.SimpleNamespace(TargetWaypointDefinition='WaypointDef B', TurnInWaypointDefinition='TurnIn B')
    # WillowPlayerController.MissionPlaythroughData[].MissionList[] {MissionDef, Status}; 1 = MS_Active
    status_a = Struct(MissionDef=mission_a, Status=1)
    pc.MissionPlaythroughData = [Struct(PlayThroughNumber=0, MissionList=[Struct(MissionDef=mission_b, Status=0)]),
                                 Struct(PlayThroughNumber=1, MissionList=[status_a,
                                                                          Struct(MissionDef=mission_b, Status=0)])]
    pc.GetCurrentPlaythrough = lambda: 1
    tracker = types.SimpleNamespace(ActiveMission=mission_a)
    TRACKERS.append(tracker)
    # WillowGlobals.ClientInteractiveObjects: two mission givers (none eligible yet) and a plain object
    zed = Giver('Zed', vec(-11500.0, 31800.0, 100.0))
    board = Giver('BountyBoard', vec(-12600.0, 32400.0, 100.0))
    crate = Giver('Crate', vec(-12000.0, 32000.0, 0.0), directives=0)
    GLOBALS.extend([FakeGlobals('Default__WillowGlobals', []), FakeGlobals('WillowGlobals_0', [zed, None, board, crate])])
    OBJECTS['GfxHUD.FlashInstances.hud_instance'] = TEMPLATE      # from WillowGame.u, always loaded
    stock_movie = Movie(gfx, patched=False)                      # HUD spawned before the redirect
    movie = Movie(gfx)
    pc.myHUD = HUD(stock_movie)
    landmarks = [(vec(-22012.3, 44803.3, 1370.5), 'transition'), (vec(-34304.0, -25440.0, 2413.0), 'poi')]
    helpers = []

    def factory(outer):
        h = Helper(outer, pc, landmarks)
        helpers.append(h)
        return h

    install_stubs(factory, lambda: pc)
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'sdk_mods'))
    import classic_minimap as mod
    mod.time = types.SimpleNamespace(time=lambda: clock[0])
    tick = HOOKS['WillowGame.WillowPlayerController:PlayerTick']

    def step(dt=0.06):
        clock[0] += dt
        tick(pc, None, None, None)

    def close(a, b, tol=1e-4):
        assert abs(a - b) < tol, (a, b)

    # 0a. a HUD spawned from the stock movie (before the redirect): idle, one warning, nothing created
    step(); step()
    assert mod.S.phase == 'stockhud' and CONSTRUCTED == [] and stock_movie.invokes == []

    # 0b. GfxHUD_Minimap.upk missing: redirect fails, template untouched
    assert mod.redirect() is False and TEMPLATE.MovieInfo is STOCK_INFO and LOADED == ['GfxHUD_Minimap']

    # 0c. package present: on_enable loads it and points the template at its movie
    PACKAGES['GfxHUD_Minimap'] = {'GfxHUD_Minimap.FlashMovie.HUD': MINIMAP_INFO}
    mod.on_enable()
    assert TEMPLATE.MovieInfo is MINIMAP_INFO and LOADED == ['GfxHUD_Minimap', 'GfxHUD_Minimap']
    mod.on_enable()                                    # already loaded: no second load, still redirected
    assert LOADED == ['GfxHUD_Minimap', 'GfxHUD_Minimap'] and mod.Redirect.original is STOCK_INFO

    # next level load spawns a HUD from the redirected template
    pc.myHUD = HUD(movie)

    # 1. spawn before the zone's anchor has streamed in (run 6): helper dropped at once, map hidden, retry
    WORLD.anchor_loaded = False
    step()
    assert mod.S.phase == 'anchorwait', mod.S.phase
    assert CONSTRUCTED == [('WillowGFxHelperMap', movie)]
    m = movie.root.get('map')
    assert isinstance(m, asvm.Clip), 'MinimapCreate did not attach the map'
    # docked (default): Enhanced's p1-space placement, sheared, composed with p1's transform
    assert mod.opt_position.value == 'Docked' and mod.S.dock == '16:9' and movie.GetVariableString('mmDockMode') == 'matrix'

    def check_dock(clip, lay, p1):
        mt = clip.props['_matrix']
        a, b, c, d, tx, ty = (mt.get(k) for k in ('a', 'b', 'c', 'd', 'tx', 'ty'))
        ea, eb, ec, ed, etx, ety = ENH[lay]['map']
        close(b / a, eb / ea * 100 / p1['sx'], 1e-6)              # the HUD's shear survives the composition
        k = 220.0 / 820.75 * mod.opt_dock_size.value / 100.0
        close(a, p1['sx'] / 100 * ea * k, 1e-9); close(d, ed * k, 1e-9)
        cx, cy = 64.25 + 820.75 / 2, 72.0 + 527.0 / 2              # mask centre lands on Enhanced's map spot
        close(a * cx + c * cy + tx, p1['x'] + p1['sx'] / 100 * etx, 1e-4)
        close(b * cx + d * cy + ty, p1['y'] + ety, 1e-4)
    check_dock(m, '16:9', P1_LAYOUTS['16:9'])
    p1c = movie.root.get('p1')
    close(p1c.get('echo').get('_x'), 791.5)                    # column untouched until the map shows
    assert m.get('_visible') is False, 'no zone yet: the blank map must stay hidden'
    assert helpers[0].calls == ['Init'] and not helpers[0].ObjectFlags & KEEP_ALIVE
    step(0.5)
    assert len(helpers) == 1, 'retry waits ANCHOR_RETRY'

    # 1b. anchor arrives: one call collects everything and InitMapFrame picks the zone; the helper is
    #     released before the call returns (nothing native survives the tick)
    WORLD.anchor_loaded = True
    step(0.6)
    assert mod.S.phase == 'framewait' and len(helpers) == 2
    h = helpers[1]
    assert h.calls == ['Init', 'InitMapFrame'] and not h.ObjectFlags & KEEP_ALIVE
    assert mod.S.anchor['MapFrame'] == 'Arid' and mod.S.anchor['Rotation'] == (0, 32, 0)

    # 2. real zone frame on stage -> transform computed in Python from the anchor fields, draw
    step()
    assert mod.S.phase == 'running'
    assert h.calls == ['Init', 'InitMapFrame'], 'no native helper call after collection: %r' % h.calls
    assert m.get('_visible') is False, 'visibility is decided per tick (settle rule), not at capture'
    # the decompiled anchor matrix reproduces the helper's own Transform logged in game
    game = [getattr(getattr(TRANSFORM, p), a) for p in ('XPlane', 'YPlane', 'ZPlane', 'WPlane') for a in 'XYZW']
    assert len(mod.S.xf) == 16
    for got, want in zip(mod.S.xf, game):
        assert abs(got - want) <= 1e-6 * max(1.0, abs(want)) + 1e-9, (got, want)
    close(mod.S.cs[0], COORD_SCALE.X); close(mod.S.cs[1], COORD_SCALE.Y)
    tm = movie.vm.lookup({}, 'map.maps.themap')
    ENH_ZOOM_PCT = 108.0 * 820.75 / 220.0                            # Enhanced's 108% relative to the window
    close(tm.get('_xscale'), ENH_ZOOM_PCT, 1e-4)                    # zoom "100%" = Enhanced, set by the mod
    lm = [c for c in m.get('maps').dynamic() if c.frame == 'transition'][0]
    close(lm.get('_xscale'), 820.75 / 220.0 * 100, 1e-4)            # icons at Enhanced's size too
    ms = m.get('maps')
    icons = [c for c in ms.children.values() if c.depth >= 0]
    # landmarks + interactive object + objective slot; zero-vector record, player and co-op buddy skipped
    assert sorted(c.frame for c in icons) == ['objective', 'poi', 'shop', 'transition'], [c.frame for c in icons]
    expected = landmarks + WORLD.interactive + [(slots[0].WaypointLocation, 'objective')]
    for (loc, frame) in expected:
        ic = [c for c in icons if c.frame == frame][0]
        u, v = native_tr(loc)
        close(ic.get('_x'), tm.get('_x') + u * tm.get('_width'), 0.01)
        close(ic.get('_y'), tm.get('_y') + v * tm.get('_height'), 0.01)
    objective_icon = [c for c in icons if c.frame == 'objective'][0]
    assert '_rgb' not in objective_icon.props, 'active mission: stock objective colour'
    # run 9 stuck diamond/arrow: the icon templates are hidden, every created icon is shown
    assert ms.get('landmarks').get('_visible') is False and ms.get('players').get('_visible') is False
    assert all(c.get('_visible') is True for c in icons)
    recs = [json.loads(l) for l in mod.ANCHOR_LOG.read_text().splitlines()]
    assert len(recs) == 1 and recs[0]['fields']['TextureSizeX'] == 1024 and 'Components' not in recs[0]['fields']
    assert abs(recs[0]['Transform'][0] - TRANSFORM.XPlane.X) < 1e-10 and recs[0]['level'].startswith("Level'arid_p")
    calls_after_capture = len(h.calls)

    # 3. running tick: the player icon comes from pc.Pawn (no helper), centred in the mask
    step()
    player = movie.root.get('mmPlayer')
    assert isinstance(player, asvm.Clip) and player.frame == 'player'
    mk = m.get('mask')
    cx = mk.get('_x') + mk.get('_width') / 2; cy = mk.get('_y') + mk.get('_height') / 2
    close(ms.get('_x') + player.get('_x'), cx); close(ms.get('_y') + player.get('_y'), cy)
    pu, pv = native_tr(pc.Pawn.Location)
    close(player.get('_x'), tm.get('_x') + pu * tm.get('_width'), 0.01)
    close(player.get('_rotation'), 29344 * 360.0 / 65536)
    assert len(h.calls) == calls_after_capture, 'no native helper calls per tick'

    # 3v. visibility (Enhanced's map is a child of p1; ours mirrors the game's own HUD gates + the
    #     diagnostics collector's 3 s settle). Still settling right after spawn:
    assert m.get('_visible') is False
    step(mod.SETTLE_SECONDS)                           # live levels unchanged for 3 s -> shown
    assert m.get('_visible') is True
    # shown + docked: ECHO, mission title and checklist take Enhanced's places (UpdateEchoPosition)
    e16 = ENH['16:9']
    close(p1c.get('echo').get('_x'), e16['echo'][0]); close(p1c.get('echo').get('_y'), e16['echo'][1])
    close(p1c.get('quest').get('_x'), e16['quest'][0])
    close(p1c.get('check2').get('_y'), e16['check'][1] + 16.4); close(p1c.get('check2').get('_xscale'), 92.02)
    close(p1c.get('echo').get('_xscale'), 100.04)      # echo/quest keep their authored scale (and shear)
    for label, on, off in (
            ('loading movie (blue tunnel)', lambda: setattr(pc, 'loading_movie', True),
             lambda: setattr(pc, 'loading_movie', False)),
            ('HUD off', lambda: setattr(pc.myHUD, 'bShowHUD', False), lambda: setattr(pc.myHUD, 'bShowHUD', True)),
            ('cinematic', lambda: setattr(pc, 'bCinematicMode', True), lambda: setattr(pc, 'bCinematicMode', False)),
            ('status menu', lambda: setattr(pc, 'bStatusMenuOpen', True),
             lambda: setattr(pc, 'bStatusMenuOpen', False)),
            ('dead', lambda: setattr(pc.Pawn, 'alive', False), lambda: setattr(pc.Pawn, 'alive', True)),
            ('HUD clip hidden', lambda: movie.root.get('p1').set('_visible', False),
             lambda: movie.root.get('p1').set('_visible', True))):
        on(); step()
        assert m.get('_visible') is False, label + ' must hide the minimap'
        close(p1c.get('echo').get('_x'), 791.5); close(p1c.get('check5').get('_y'), 92.4 + 4 * 19.7)
        close(p1c.get('check5').get('_xscale'), 100.04)   # hidden map: the column is back where authored
        player_x = movie.root.get('mmPlayer').get('_x')
        off(); step()
        assert m.get('_visible') is True, label + ' cleared: minimap back'
        close(p1c.get('echo').get('_x'), e16['echo'][0])
    # a level streams in (e.g. travel) -> hidden while it settles, back after 3 s; no flicker on rebuild
    world.StreamingLevels.append(types.SimpleNamespace(bIsVisible=True, LoadedLevel='Level arid_settle.TheWorld'))
    step(0.3)
    assert m.get('_visible') is False
    world.StreamingLevels.pop()
    step(0.3); step(); step()                          # rebuild for the area change runs while hidden
    assert m.get('_visible') is False
    step(mod.SETTLE_SECONDS); step()
    assert m.get('_visible') is True and mod.S.phase == 'running'
    # a failing check never hides the map for good or resets it
    pc.IsLoadingMoviePlaying = None                    # calling it raises TypeError
    step()
    assert m.get('_visible') is True and mod.S.phase == 'running'
    # ...and it doesn't disable the other checks (run 8: a missing pawn.Health turned them all off)
    pc.bStatusMenuOpen = True
    step()
    assert m.get('_visible') is False, 'status menu must still hide the map while another check is broken'
    pc.bStatusMenuOpen = False
    step()
    assert m.get('_visible') is True
    pc.IsLoadingMoviePlaying = lambda: pc.loading_movie

    # objective moves within the same mission (run 8 stale diamond): rebuild with fresh markers;
    # drift smaller than the rounding grid doesn't rebuild
    n = len(helpers)
    step(0.6)
    slots[0].WaypointLocation = vec(-12020.0, 33010.0, 100.0)     # < WAYPOINT_GRID: same key
    step(0.6); step(); step()
    assert len(helpers) == n, 'sub-grid drift must not rebuild'
    slots[0].WaypointLocation = vec(-9000.0, 36000.0, 300.0)      # the objective moved
    # run 9 flicker: the rebuild happens in place within one tick, the map is never hidden or emptied
    movie.visible_sets.clear()
    step(0.6)
    assert len(helpers) == n + 1 and mod.S.phase == 'running' and mod.S.movie is movie
    assert False not in movie.visible_sets, 'an in-place rebuild must not hide the map'
    msx = m.get('maps')
    assert isinstance(movie.root.get('mmPlayer'), asvm.Clip) and movie.root.get('mmPlayer').get('_visible') is True
    marks_now = [c for c in msx.dynamic() if c.frame in ('objective', 'poi', 'shop', 'transition')]
    assert len(marks_now) == 4, 'markers swapped in the same tick: %r' % [c.frame for c in marks_now]
    ox, oy = native_tr(slots[0].WaypointLocation)
    tmx = msx.get('themap')
    obj_icon = [c for c in marks_now if c.frame == 'objective'][0]
    close(obj_icon.get('_x'), tmx.get('_x') + ox * tmx.get('_width'), 0.01)
    assert m.get('_visible') is True
    step(); step()
    slots[1].WaypointLocation = vec(-5000.0, 30000.0, 0.0)        # a second objective appears
    step(0.6); step(); step()
    assert len(helpers) == n + 2
    step(mod.SETTLE_SECONDS)
    assert m.get('_visible') is True, 'objective rebuilds must not trigger the settle hide'
    player = movie.root.get('mmPlayer')
    ms = m.get('maps')

    # 4. player moves -> still centred
    pc.Pawn.Location = vec(-15000.0, 30000.0, 100.0)
    step()
    close(ms.get('_x') + player.get('_x'), cx); close(ms.get('_y') + player.get('_y'), cy)

    # 5. threats come from the compass radar's replicated list (Enhanced's UpdateThreats source): every
    #    active entry, no range filter by default; inactive entries ignored; pawns not scanned
    assert mod.opt_threat_range.value == 0 and mod.S.threat_source == 'radar'
    enemy.Location = vec(-14500.0, 30500.0, 100.0)
    radar.RemoteDynamicIcons[3] = radar_icon(vec(-14500.0, 30500.0, 100.0), active=True)
    radar.RemoteDynamicIcons[7] = radar_icon(vec(-5000.0, 20000.0, 0.0), active=True, icon_type=1)   # gunfire, far
    radar.RemoteDynamicIcons[9] = radar_icon(vec(-14000.0, 30000.0, 0.0), active=False)
    step(0.3)
    pool = movie.root.get('mmThreats')
    visible = [c for c in pool if c.get('_visible')]
    assert len(visible) == 2, [(c.get('_x'), c.get('_y'), c.get('_visible')) for c in pool]
    for want in (radar.RemoteDynamicIcons[3].Location, radar.RemoteDynamicIcons[7].Location):
        ex, ey = native_tr(want)
        assert any(abs(c.get('_x') - (tm.get('_x') + ex * tm.get('_width'))) < 0.05 and
                   abs(c.get('_y') - (tm.get('_y') + ey * tm.get('_height'))) < 0.05 for c in visible), want
    mod.opt_threat_range.value = 60                    # optional range filter: the far gunfire icon drops out
    step(0.3)
    visible = [c for c in pool if c.get('_visible')]
    assert len(visible) == 1
    ex, ey = native_tr(enemy.Location)
    close(visible[0].get('_x'), tm.get('_x') + ex * tm.get('_width'), 0.05)  # 5-decimal threat string
    mod.opt_threat_range.value = 0
    mod.opt_threats.value = False
    step(0.3)
    assert not any(c.get('_visible') for c in pool), 'Show enemies off must hide dots'
    mod.opt_threats.value = True

    # 5b. radar list stays empty while an enemy stands close: after RADAR_MISS_LIMIT probes the mod
    #     switches to the pawn scan (only the live enemy, not the dead one)
    for icon in radar.RemoteDynamicIcons:
        icon.bActive = False
    dead.Location = vec(-14900.0, 30100.0, 100.0)
    enemy.Location = vec(-14600.0, 30400.0, 100.0)     # ~570 uu: inside the probe range
    for _ in range(mod.RADAR_PROBE_EVERY * mod.RADAR_MISS_LIMIT - 1):
        step(mod.THREAT_INTERVAL + 0.01)
    assert mod.S.threat_source == 'radar'
    step(mod.THREAT_INTERVAL + 0.01)
    assert mod.S.threat_source == 'pawns'
    step(mod.THREAT_INTERVAL + 0.01)
    visible = [c for c in pool if c.get('_visible')]
    assert len(visible) == 1
    ex, ey = native_tr(enemy.Location)
    close(visible[0].get('_x'), tm.get('_x') + ex * tm.get('_width'), 0.05)
    # 5c. no radar manager at all: pawn scan straight away
    mod.S.threat_source, mod.S.radar_empty, mod.S.radar_misses = 'radar', 0, 0
    world.GRI.RadarMgr = None
    step(mod.THREAT_INTERVAL + 0.01)
    assert mod.S.threat_source == 'pawns' and len([c for c in pool if c.get('_visible')]) == 1
    world.GRI.RadarMgr = radar
    mod.S.threat_source = 'radar'

    # 6. rotation: maps rotated so the player faces up, player still centred
    mod.opt_rotate.value = True
    step()
    close(ms.get('_rotation'), 0 - player.get('_rotation'))
    R = math.radians(ms.get('_rotation'))
    sx = ms.get('_x') + player.get('_x') * math.cos(R) - player.get('_y') * math.sin(R)
    sy = ms.get('_y') + player.get('_x') * math.sin(R) + player.get('_y') * math.cos(R)
    close(sx, cx); close(sy, cy)
    mod.opt_rotate.value = False

    # 7. option change applies on the next tick (layout + zoom + compass). Custom position: the sliders,
    #    no shear left over, the HUD column restored
    mod.opt_position.value = 'Custom'
    mod.opt_scale.value, mod.opt_zoom.value, mod.opt_hide_compass.value = 40, '150%', True
    mod.mark_layout_dirty()
    step()
    close(m.get('_xscale'), 40); close(tm.get('_xscale'), ENH_ZOOM_PCT * 1.5, 1e-4)
    s = mod.opt_scale.value / 100.0
    close(m.get('_x') + 885.0 * s, 1280.0 - mod.opt_margin_x.value)
    assert m.props['_matrix'].get('b') == 0.0 and mod.S.dock is None
    assert movie.root.get('p1').get('bearing').get('_visible') is False
    close(p1c.get('echo').get('_x'), 791.5); close(p1c.get('quest').get('_x'), 545.0)
    # back to docked, at 120%: shear and centre as before, column moved aside again
    mod.opt_position.value, mod.opt_dock_size.value = 'Docked', 120
    mod.mark_layout_dirty()
    step()
    check_dock(m, '16:9', P1_LAYOUTS['16:9'])
    close(p1c.get('echo').get('_x'), e16['echo'][0])
    mod.opt_dock_size.value = 100
    mod.mark_layout_dirty(); step()

    # 7a. HUD layout switch (4:3): the root places a new p1 instance -> re-docked within a second with the
    #     4:3 placement; the new p1's column is recorded from its own authored values and moved
    movie.root.children.pop('p1')
    p1c = movie.add_p1(P1_LAYOUTS['4:3'])
    step(mod.DOCK_CHECK_INTERVAL + 0.01); step()
    assert mod.S.dock == '4:3'
    check_dock(m, '4:3', P1_LAYOUTS['4:3'])
    close(p1c.get('echo').get('_x'), ENH['4:3']['echo'][0]); close(p1c.get('quest').get('_y'), ENH['4:3']['quest'][1])
    close(movie.GetVariableNumber('mmEchoX0'), 655.5)
    pc.bStatusMenuOpen = True; step()
    close(p1c.get('echo').get('_x'), 655.5)            # hidden -> 4:3 authored place, not 16:9's
    pc.bStatusMenuOpen = False; step()
    movie.root.children.pop('p1')
    p1c = movie.add_p1(P1_LAYOUTS['16:9'])
    step(mod.DOCK_CHECK_INTERVAL + 0.01); step()
    assert mod.S.dock == '16:9'
    check_dock(m, '16:9', P1_LAYOUTS['16:9'])

    # 7b. zoom change re-places every landmark relative to the re-scaled art
    ic = [c for c in ms.children.values() if c.depth >= 0 and c.frame == 'poi'][0]
    u, v = native_tr(landmarks[1][0])
    close(ic.get('_x'), tm.get('_x') + u * tm.get('_width'), 0.01)

    # 7b'. mission givers (PLAN_V08 3): classic's own GetEligibleMissions / GetRedeemableMissions per giver
    def icons_of(frame):
        return [c for c in m.get('maps').dynamic() if c.frame == frame]
    assert icons_of('newmission') == [] and icons_of('turnin') == []
    n = len(helpers)
    zed.eligible = 1                                   # a mission becomes available at Zed
    step(0.6)                                          # giver state is part of the key -> in-place rebuild
    assert len(helpers) == n + 1 and mod.S.phase == 'running'
    assert len(mod.S.givers) == 2, 'only interactive objects with mission directives are givers'
    bang = icons_of('newmission')
    assert len(bang) == 1 and bang[0].get('_visible') is True
    tmz = m.get('maps').get('themap')
    zu, zv = native_tr(zed.Location)
    close(bang[0].get('_x'), tmz.get('_x') + zu * tmz.get('_width'), 0.01)
    zed.eligible, board.redeemable = 0, 1              # accepted at Zed; a finished bounty can be handed in
    step(0.6)
    assert len(helpers) == n + 2 and icons_of('newmission') == [] and len(icons_of('turnin')) == 1
    zed.eligible, zed.fail = 1, True                   # a failing script call: skipped, warned once, map runs
    step(0.6); step(0.6)
    assert mod.S.phase == 'running' and len(icons_of('turnin')) == 1 and icons_of('newmission') == []
    zed.fail = False
    step(0.6)
    assert len(icons_of('newmission')) == 1
    mod.opt_givers.value = False                       # option off: rebuilt without givers
    mod.opt_givers.on_change_while_enabled(mod.opt_givers, False); step(); step()
    assert icons_of('newmission') == [] and icons_of('turnin') == [] and mod.S.givers == []
    mod.opt_givers.value = True
    mod.opt_givers.on_change_while_enabled(mod.opt_givers, True); step(); step()
    zed.eligible = board.redeemable = 0
    step(0.6); step()
    assert icons_of('newmission') == [] and icons_of('turnin') == []
    ms = m.get('maps')
    player = movie.root.get('mmPlayer')

    # 7c. tracked mission becomes ready to turn in: the status is part of the rebuild key and the
    #     objective diamond is tinted gold (classic art has no Enhanced "turnin" frame)
    n = len(helpers)
    status_a.Status = 2
    step(0.6); step(); step()
    assert len(helpers) == n + 1 and mod.S.phase == 'running' and mod.S.tint == mod.STATUS_TINT[2]
    ms = m.get('maps')
    obj = [c for c in ms.children.values() if c.depth >= 0 and c.frame == 'objective']
    assert len(obj) == 2 and all(c.props.get('_rgb') == 0xFFC420 for c in obj), [c.props for c in obj]  # slots 0, 1
    assert all('_rgb' not in c.props for c in ms.children.values() if c.depth >= 0 and c.frame != 'objective')
    status_a.Status = 1
    step(0.6); step(); step()
    assert len(helpers) == n + 2 and mod.S.tint is None
    # mission data unreadable: no tint, the map still runs
    saved = pc.MissionPlaythroughData
    del pc.MissionPlaythroughData
    KEYBINDS['Rebuild minimap'](); step(); step()
    assert mod.S.phase == 'running' and mod.S.tint is None
    pc.MissionPlaythroughData = saved
    step(0.6); step(); step()                          # status readable again -> key changes once
    assert mod.S.phase == 'running'
    recs = [json.loads(l) for l in mod.ANCHOR_LOG.read_text().splitlines()]
    assert len(recs) == 1, 'each anchor is logged once per session, not on every rebuild'
    ms = m.get('maps')
    player = movie.root.get('mmPlayer')

    # 8. rebuild (F8 / status menu close) starts over: a new transient helper, released after capture
    n = len(helpers)
    KEYBINDS['Rebuild minimap']()
    step(); step()
    assert mod.S.phase == 'running' and len(helpers) == n + 1
    assert not any(x.ObjectFlags & KEEP_ALIVE for x in helpers), 'no helper may stay pinned'

    # 8a. tracked mission changes (e.g. Mission Selector): fresh helper, no FindObjects append on the old one
    n = len(helpers)
    step(0.6)                                          # first objective check after the rebuild records the key
    assert len(helpers) == n
    tracker.ActiveMission = mission_b
    step(0.6)                                          # key changed -> rebuild
    step(); step()
    assert len(helpers) == n + 1 and mod.S.phase == 'running', (len(helpers), mod.S.phase)
    assert not any(x.ObjectFlags & KEEP_ALIVE for x in helpers)
    step(0.6); step(0.6)                               # unchanged key: no further rebuilds
    assert len(helpers) == n + 1

    # 8a'. an area streams in: landmarks for it need a fresh helper too
    world.StreamingLevels.append(types.SimpleNamespace(bIsVisible=True, LoadedLevel='Level arid_mine.TheWorld'))
    step(0.6); step(); step()
    assert len(helpers) == n + 2 and mod.S.phase == 'running'
    step(0.6)
    assert len(helpers) == n + 2
    world.StreamingLevels.pop()
    step(0.6); step(); step()
    assert len(helpers) == n + 3

    # 8a''. objective lookup failing is non-fatal: the map keeps running, no rebuild loop
    TRACKERS.clear(); mod.S.tracker = mod.WeakPointer()
    world_levels = world.StreamingLevels
    world.StreamingLevels = None                       # iterating it raises TypeError
    step(0.6); step(0.6)
    assert mod.S.phase == 'running' and len(helpers) == n + 3
    world.StreamingLevels = world_levels; TRACKERS.append(tracker)

    # 8b. the engine destroys the HUD movie (level unload) while GetHUDMovie briefly returns nothing:
    #     the weak reference reads None, the mod resets and touches nothing that was freed
    movie.destroyed = True
    pc.myHUD = HUD(None)
    live = helpers[-1]
    step()
    assert mod.S.movie is None and mod.S.phase == 'idle' and not live.ObjectFlags & KEEP_ALIVE
    movie.destroyed = False
    pc.myHUD = HUD(movie)
    n = len(helpers)
    step(); step()
    assert mod.S.phase == 'running' and len(helpers) == n + 1

    # 9. new HUD movie (level change) -> fresh start on the new movie
    movie2 = Movie(gfx)
    pc.myHUD = HUD(movie2)
    step(); step()
    assert mod.S.movie is movie2 and mod.S.phase == 'running' and len(helpers) == n + 2

    # 10. unpatched HUD: retries once a second, never constructs a helper, gives up after MAX_ATTEMPTS
    movie3 = Movie(gfx, patched=False, info=MINIMAP_INFO)   # right movie, root code never runs
    pc.myHUD = HUD(movie3)
    n = len(helpers)
    step()
    assert mod.S.phase == 'retry' and len(helpers) == n
    for _ in range(mod.MAX_ATTEMPTS + 2):
        step(mod.RETRY_INTERVAL + 0.01)
    assert mod.S.phase == 'nopatch' and len(helpers) == n and mod.S.attempts == mod.MAX_ATTEMPTS

    # 10b. root functions appear late (HUD movie hasn't run its frame-1 script yet): retry succeeds
    movie4 = Movie(gfx, patched=False, info=MINIMAP_INFO)
    pc.myHUD = HUD(movie4)
    step(); step(mod.RETRY_INTERVAL + 0.01)
    assert mod.S.phase == 'retry'
    for code, body, _ in top_level(gfx):
        if code == 12:
            movie4.vm.define(as2asm.decode(body))
    step(mod.RETRY_INTERVAL + 0.01); step()
    assert mod.S.phase == 'running' and mod.S.movie is movie4, mod.S.phase

    # 10b'. anchor present but the zone frame never becomes real (stays "none"): give up after
    #       READY_TIMEOUT, release the helper, retry; succeeds once the frame works
    WORLD.zone_frame = 'none'
    movie7 = Movie(gfx)
    pc.myHUD = HUD(movie7)
    n = len(helpers)
    step(); step(); step()
    assert mod.S.phase == 'framewait' and not helpers[-1].ObjectFlags & KEEP_ALIVE
    step(mod.READY_TIMEOUT + 0.1)
    assert mod.S.phase == 'anchorwait'
    WORLD.zone_frame = 'arid'
    step(mod.ANCHOR_RETRY + 0.1); step()
    assert mod.S.phase == 'running' and len(helpers) == n + 2

    # 10b''. a degenerate anchor (zero texture size) can't be inverted: no map, no crash, retried
    try:
        mod.anchor_transform(dict(mod.S.anchor, TextureSize=(0.0, 512.0)))
        raise AssertionError('singular anchor matrix must raise')
    except ValueError:
        pass
    FakeAnchor.TextureSizeX = 0
    movie8 = Movie(gfx)
    pc.myHUD = HUD(movie8)
    step(); step(); step()
    assert mod.S.phase == 'framewait' and movie8.root.get('map').get('_visible') is False
    FakeAnchor.TextureSizeX = 1024
    step(mod.READY_TIMEOUT + 0.1); step(mod.ANCHOR_RETRY + 0.1); step()
    assert mod.S.phase == 'running'

    # 10c. no pawn (main menu / loading): nothing starts
    movie5 = Movie(gfx)
    pawn = pc.Pawn
    pc.Pawn = None
    pc.myHUD = HUD(movie5)
    step(); step()
    assert movie5.invokes == [] and mod.S.movie is not movie5
    pc.Pawn = pawn

    # 10d. attachMovie fails under the game's Scaleform: the timeline fallback is used and the map runs
    asvm.Clip.attach_works = False
    try:
        movie6 = Movie(gfx)
        pc.myHUD = HUD(movie6)
        step(); step(); step()
        assert mod.S.phase == 'running' and movie6.GetVariableString('mmCreateMode') == 'fallback'
        assert movie6.root.get('mmfallback') is UNDEF and isinstance(movie6.root.get('map'), asvm.Clip)
        mp = movie6.root.get('map'); mk6, ms6 = mp.get('mask'), mp.get('maps')
        pl = movie6.root.get('mmPlayer')
        close(ms6.get('_x') + pl.get('_x'), mk6.get('_x') + mk6.get('_width') / 2)
    finally:
        asvm.Clip.attach_works = True

    # 10e. runtime without MovieClip.transform: docked position and size without the shear, logged
    asvm.Clip.transform_works = False
    try:
        movie9 = Movie(gfx)
        pc.myHUD = HUD(movie9)
        step(); step(); step()
        assert mod.S.phase == 'running' and movie9.GetVariableString('mmDockMode') == 'plain'
        assert mod.S.dock == '16:9' and mod.S.dock_mode == 'plain'
        m9 = movie9.root.get('map')
        k = 220.0 / 820.75
        close(m9.get('_xscale'), 0.698 * k * 100, 1e-6)
    finally:
        asvm.Clip.transform_works = True

    # 11. disable tears the map down, restores the compass and the HUD column
    pc.myHUD = HUD(movie2)
    step(); step()
    step(mod.SETTLE_SECONDS); step()
    p1d = movie2.root.get('p1')
    assert movie2.root.get('map').get('_visible') is True
    close(p1d.get('echo').get('_x'), ENH['16:9']['echo'][0])
    # F7 diagnostics: runs against the live state and logs every field (v0.8 added givers/zoom/icon scale)
    import contextlib
    import io as _io
    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf):
        KEYBINDS['Minimap diagnostics']()
    diag = buf.getvalue()
    assert 'diagnostics:' in diag and "'version': '%s'" % mod.__version__ in diag, diag[:300]
    for field in ('dock_mode', 'radar_active', 'givers', 'giver_icons', 'zoom', 'icon_scale', 'echo_x0'):
        assert "'%s'" % field in diag, field
    mod.on_disable()
    assert movie2.root.get('map') is UNDEF and p1d.get('bearing').get('_visible') is True
    close(p1d.get('echo').get('_x'), 791.5); close(p1d.get('check1').get('_xscale'), 100.04)
    assert TEMPLATE.MovieInfo is STOCK_INFO, 'disable must restore the stock HUD movie'
    print('all minimap mod integration checks passed')


if __name__ == '__main__':
    main(sys.argv[1])
