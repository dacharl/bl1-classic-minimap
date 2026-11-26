"""Offline integration test: the real classic_minimap mod + the real built HUD movie's ActionScript.

Usage: python -I tools/test_minimap_mod.py dist/phase2/HUD_minimap.gfx

unrealsdk / mods_base are stubbed. movie.Invoke runs root functions in tools/test_minimap_as.py's AS2
interpreter, decoded from the built movie. The WillowGFxHelperMap natives are emulated with the behaviour
measured in game (PHASE0 2d) and decompiled (ENHANCED_NATIVE.md): Init builds MapObjectData records with
the real field names, InitMapFrame picks the zone frame. The expected Transform/CoordScale are the helper's
own values logged in game for the Arid anchor; the mod must reproduce them from the anchor's fields.
"""
import contextlib
import io
import json
import math
import os
import re
import struct
import sys
import types
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import as2asm  # noqa: E402
import test_minimap_as as asvm  # noqa: E402
from swfbuild import top_level  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'sdk_mods', 'classic_minimap'))
import swfmerge  # noqa: E402

UNDEF = Ellipsis


# ---- stubs for unrealsdk / mods_base -----------------------------------------------------------
class Struct(types.SimpleNamespace):
    pass


class Obj(Struct):
    """A UObject stand-in: str() is its stable path name, as in pyunrealsdk (not its fields)."""

    def __str__(self):
        return self._name


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


MOVIE_INFOS = []        # GFxMovieInfo objects constructed from Python (the runtime HUD merge)
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
        if cls == 'GFxMovieInfo':
            obj = Struct(**vars(template_obj))      # properties come from the template, like the engine's archetype
            obj.ObjectFlags, obj.Name, obj.RawData = flags, name, []
            obj.name = "GFxMovieInfo'%s.%s'" % (outer, name)       # its own path, not the template's
            MOVIE_INFOS.append(obj)
            return obj
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
    # <Borderlands>/sdk_mods/settings: the mod finds the game folder (and its HUD packages) from here (PLAN_V13)
    mb.SETTINGS_DIR = Path(tempfile.mkdtemp(prefix='mm_game_')) / 'Borderlands' / 'sdk_mods' / 'settings'
    mb.SETTINGS_DIR.mkdir(parents=True)

    class Opt:
        def __init__(self, identifier, value=None, *a, **kw):
            self.identifier, self.value, self.args, self.kw = identifier, value, a, kw
            self.on_change_while_enabled = kw.get('on_change_while_enabled')
            for k, v in kw.items():
                setattr(self, k, v)

    for n in ('BoolOption', 'SliderOption', 'SpinnerOption', 'ButtonOption', 'HiddenOption'):
        setattr(mb, n, type(n, (Opt,), {}))

    class Group:
        def __init__(self, identifier, children, **kw):
            self.identifier, self.children, self.kw = identifier, list(children), kw

    mb.GroupedOption, mb.NestedOption = type('GroupedOption', (Group,), {}), type('NestedOption', (Group,), {})

    def hook(name, typ='PRE', **kw):
        def deco(f):
            HOOKS.setdefault(name, f)                   # the first hook on a function, by name...
            HOOKS['%s:%s' % (name, str(typ).lower())] = f   # ...and every hook by name and type
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
        before = maps.frame
        target = WORLD.zone_frame if self.Anchor is not None else 'none'
        maps.as_gotoAndStop(target)
        # DLC zones (MapFrame dlcmap1, DLCMap set): the native calls InitDLC, and the dlcmap1 frame's action
        # loadMovie(_root.LoadDLCPackage) runs only when the playhead *enters* the frame (status menu sprite
        # 1132 frame 30). Already on dlcmap1, gotoAndStop is a no-op and the old DLC movie stays (run 14).
        if self.Anchor is not None and self.Anchor.DLCMap is not None and before != target:
            WORLD.loaded_dlc = str(self.Anchor.DLCMap)
        return True

    def InitMapFrameVars(self, movie):
        raise AssertionError('v0.6 computes ClipSize/CoordScale itself; InitMapFrameVars must not be called')

    def UpdateObjects(self, static):
        raise AssertionError('v0.6 projects in Python; UpdateObjects must not be called')


def foreign_from(gfx, extra_id=5000, prefix_tag=False):
    """Another mod's HUD movie, derived from ours: stock-shaped (no block, no manifest, its own gradient image
    numbering) plus a character of its own after the first frame, like Extended UI's."""
    info, _ = swfmerge.read_block(gfx)
    head, root, trailing = swfmerge.split(gfx)
    m = next(i for i, (c, b, _) in enumerate(root) if c == swfmerge.METADATA)
    kept = root[:m] + root[m + 1 + info['tags']:]
    limit = info['gradients_before'] + info['gradients']
    out = []
    for c, b, r in kept:
        if c == swfmerge.GRADIENT_IMAGE and struct.unpack_from('<H', b, 0)[0] >= limit:
            b = struct.pack('<H', struct.unpack_from('<H', b, 0)[0] - info['gradients']) + b[2:]
            r = swfmerge.tag(c, b)
        out.append((c, b, r))
    if prefix_tag:      # a tag stock doesn't have before its first frame
        out.insert(0, (43, b"x", swfmerge.tag(43, b"x")))
    at = swfmerge.first_show(out)
    extra = swfmerge.tag(39, struct.pack('<HH', extra_id, 1) + swfmerge.tag(1, b'') + swfmerge.tag(0, b''))
    data = bytearray(head + b''.join(r for _, _, r in out[:at + 1]) + extra + b''.join(r for _, _, r in out[at + 1:])
                     + trailing)
    struct.pack_into('<I', data, 4, len(data))
    return bytes(data)


def main(gfx_path, on_import=None):
    """on_import(mod), if given, runs right after the real mod is imported (the profiler add-on's tests
    attach a capture there and expect every assertion below to hold unchanged)."""
    global MINIMAP_INFO         # becomes the GFxMovieInfo the mod constructs from the player-built movie (0c)
    gfx = Path(gfx_path).read_bytes()
    MINIMAP_INFO.RawData = gfx
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
    if on_import is not None:
        on_import(mod)
    tick = HOOKS['WillowGame.WillowPlayerController:PlayerTick']

    def step(dt=0.06):
        clock[0] += dt
        tick(pc, None, None, None)

    def close(a, b, tol=1e-4):
        assert abs(a - b) < tol, (a, b)

    # 0a. a HUD spawned from the stock movie (before the redirect): idle, one warning, nothing created
    step(); step()
    assert mod.S.phase == 'stockhud' and CONSTRUCTED == [] and stock_movie.invokes == []

    # The player-built movie (PLAN_V13): the mod builds our movie from the game folder's own HUD packages. The
    # builder itself is covered by test_hudmovie/test_ci; here it returns the movie under test, and Steam's
    # library list is empty, so Enhanced is not found (original art).
    builds = []

    def build_movie(hud_package, menus_package, enhanced_package, version):
        builds.append((hud_package, menus_package, enhanced_package, version))
        return gfx, 'enhanced' if enhanced_package else 'original', []
    mod.hudmovie.build_movie = build_movie
    mod.hudmovie.default_vdfs = lambda game: []
    interface = mod.hudmovie.game_dir(mod.SETTINGS_DIR) / mod.hudmovie.INTERFACE

    # 0b. the game's HUD packages missing: redirect fails with a status line, template untouched, no package load
    assert mod.redirect() is False and TEMPLATE.MovieInfo is STOCK_INFO and LOADED == [] and builds == []
    assert "Can't build the minimap's HUD movie" in mod.Redirect.status and 'stays idle' in mod.Redirect.status

    # 0c. packages present: on_enable builds the movie once, caches it, and points the template at a GFxMovieInfo
    # constructed from it (KEEP_ALIVE, properties copied from the stock movie, so its textures resolve)
    interface.mkdir(parents=True)
    (interface / 'GfxHUD.upk').write_bytes(b'classic hud package')
    (interface / 'menus_ingame_redux.upk').write_bytes(b'classic menus package')
    (interface / 'GfxHUD_Minimap.upk').write_bytes(b'an old v0.12 package')
    out0 = io.StringIO()
    with contextlib.redirect_stdout(out0):
        mod.on_enable()
    info = TEMPLATE.MovieInfo
    assert info is MOVIE_INFOS[-1] and info is not STOCK_INFO and bytes(info.RawData) == gfx
    assert info.ObjectFlags & KEEP_ALIVE and info.Name == 'MinimapHUD' and LOADED == []
    assert len(builds) == 1 and builds[0][2] is None and builds[0][3] == mod.__version__
    assert (mod.SETTINGS_DIR / mod.hudmovie.CACHE_NAMES[True]).read_bytes() == gfx
    assert 'original art' in mod.Redirect.status, mod.Redirect.status
    assert 'GfxHUD_Minimap.upk is no longer used' in out0.getvalue(), 'the old package is pointed out'
    MINIMAP_INFO = info
    constructed = len(MOVIE_INFOS)
    mod.on_enable()                                    # same session: no rebuild, no second object
    assert TEMPLATE.MovieInfo is MINIMAP_INFO and len(builds) == 1 and len(MOVIE_INFOS) == constructed
    assert mod.Redirect.original is STOCK_INFO
    # the next session reads the movie cache instead of building (and constructs its own object)
    mod.on_disable()
    mod.Redirect.result = None
    mod.on_enable()
    assert len(builds) == 1 and bytes(TEMPLATE.MovieInfo.RawData) == gfx and mod.Redirect.result.cached
    MINIMAP_INFO = TEMPLATE.MovieInfo
    # "Use Enhanced artwork" off, then "Rebuild HUD movie": each builds a new movie and re-points the template
    out1 = io.StringIO()
    with contextlib.redirect_stdout(out1):
        mod.opt_enhanced_art.on_change_while_enabled(mod.opt_enhanced_art, False)
        mod.opt_enhanced_art.value = False
        assert len(builds) == 2 and TEMPLATE.MovieInfo is MOVIE_INFOS[-1] and TEMPLATE.MovieInfo is not MINIMAP_INFO
        mod.opt_rebuild_movie.on_press(mod.opt_rebuild_movie)
        assert len(builds) == 3 and TEMPLATE.MovieInfo is MOVIE_INFOS[-1] and mod.Redirect.original is STOCK_INFO
        mod.opt_enhanced_art.on_change_while_enabled(mod.opt_enhanced_art, True)
        mod.opt_enhanced_art.value = True
    assert len(builds) == 3, 'switching back reads that choice\'s own movie cache'
    assert 'no longer used' not in out1.getvalue(), 'the old-package note is logged once per session'
    MINIMAP_INFO = TEMPLATE.MovieInfo
    movie.MovieInfo = MINIMAP_INFO                     # spawned from the template after the redirect

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
        k = mod.opt_dock_size.value / 100.0                         # PLAN_V09: Enhanced's own clip layout
        close(a, p1['sx'] / 100 * ea * k, 1e-9); close(d, ed * k, 1e-9)
        close(tx, p1['x'] + p1['sx'] / 100 * etx, 1e-4)             # clip origin (= window centre) lands on
        close(ty, p1['y'] + ety, 1e-4)                               # Enhanced's map spot in p1
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
    ENH_ZOOM_PCT = 400.0                    # nearby objective fits at Enhanced's maximum (PLAN_V10)
    close(tm.get('_xscale'), ENH_ZOOM_PCT, 1e-4)                    # zoom "100%" = Enhanced, set by the mod
    lm = [c for c in m.get('maps').dynamic() if c.frame == 'transition'][0]
    close(lm.get('_xscale'), 100, 1e-4)                              # icons at Enhanced's size too
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
    assert asvm.tint_of(objective_icon) is None, 'active mission: stock objective colour'
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
        off(); step()
        assert m.get('_visible') is True, label + ' cleared: minimap back'
        close(p1c.get('echo').get('_x'), e16['echo'][0])
    # Run 25 (Deck): the game re-plays p1's first frame, putting ECHO back behind the map with the shift still on.
    # Run 41: before any reset mmHudFixes is undefined; F7 said 'hud_fixes': inf
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        KEYBINDS['Minimap diagnostics']()
    assert "'hud_fixes': 0" in buf.getvalue(), buf.getvalue()[-300:]
    mod.S.warned.discard('diag-console')          # the viewport console's once-only warning is checked further down
    # The next tick moves the column again; the once-a-second check logs it, and F7 counts it.
    for n, (x, y) in P1_LAYOUTS['16:9']['column'].items():
        p1c.get(n).props.update(_x=x, _y=y, _xscale=100.04)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        step()
        close(p1c.get('echo').get('_x'), e16['echo'][0]); close(p1c.get('quest').get('_x'), e16['quest'][0])
        step(mod.DOCK_CHECK_INTERVAL)
    assert 'the game put the ECHO panel back behind the map; moved it again (1 time)' in buf.getvalue(), buf.getvalue()
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
    # Size keeps its pre-v0.9 meaning: the window is 820.75 px x Size% wide; its top-right corner at the margins
    s = 820.75 * 0.40 / 207.95
    close(m.get('_xscale'), s * 100, 1e-4); close(tm.get('_xscale'), ENH_ZOOM_PCT * 1.5, 1e-4)
    close(207.95 * s, 820.75 * 0.40, 1e-6)
    close(m.get('_x') + 104.0 * s, 1280.0 - mod.opt_margin_x.value, 1e-3)
    close(m.get('_y') - 86.8 * s, mod.opt_margin_y.value, 1e-3)
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

    # 7c. tracked mission becomes ready to turn in: the status is part of the rebuild key, and like Enhanced
    #     (FUN_14138d240, PHASE3 3ak) the objective slots are drawn with the "turnin" frame, untinted, instead
    #     of the diamond. Enhanced's edge indicator follows only "objective" frames, so turn-ins get none.
    def frames_on_map():
        return [(c.frame, asvm.tint_of(c)) for c in m.get('maps').children.values() if c.depth >= 0]
    n = len(helpers)
    status_a.Status = 2
    step(0.6); step(); step()
    assert len(helpers) == n + 1 and mod.S.phase == 'running' and mod.S.tint is None
    assert mod.S.objective_frame == 'turnin'
    marks = frames_on_map()
    assert marks.count(('turnin', None)) == 2 and not any(f == 'objective' for f, _ in marks), marks  # slots 0, 1
    assert all(t is None for _, t in marks)
    # a giver standing on the objective (the turn-in NPC) adds no second mark there; givers elsewhere still do
    board_loc = board.Location
    slot = slots[0].WaypointLocation
    board.Location, board.redeemable, zed.eligible = vec(slot.X + 100.0, slot.Y, slot.Z), 1, 1
    step(0.6); step(); step()
    marks = frames_on_map()
    assert marks.count(('turnin', None)) == 2 and marks.count(('newmission', None)) == 1, marks
    board.Location, board.redeemable, zed.eligible = board_loc, 0, 0
    # 7c'. "Tint objective diamonds" keeps the pre-v0.13.1 style: the diamond, tinted gold when ready to hand in
    mod.opt_objective_tint.value = True
    mod.opt_objective_tint.on_change_while_enabled(mod.opt_objective_tint, True); step(); step()
    assert mod.S.objective_frame == 'objective' and mod.S.tint == mod.STATUS_TINT[2]
    obj = [c for c in m.get('maps').children.values() if c.depth >= 0 and c.frame == 'objective']
    assert len(obj) == 2 and all(asvm.tint_of(c) == 0xFFC420 for c in obj), [c.props for c in obj]
    assert all(t is None for f, t in frames_on_map() if f != 'objective')
    status_a.Status = 0                                # not started: green diamond (tinted) ...
    step(0.6); step(); step()
    assert mod.S.tint == mod.STATUS_TINT[0] and mod.S.objective_frame == 'objective'
    mod.opt_objective_tint.value = False               # ... or Enhanced's "!" (newmission frame)
    mod.opt_objective_tint.on_change_while_enabled(mod.opt_objective_tint, False); step(); step()
    assert mod.S.objective_frame == 'newmission' and frames_on_map().count(('newmission', None)) == 2
    status_a.Status = 1
    step(0.6); step(); step()
    assert mod.S.tint is None and mod.S.objective_frame == 'objective'
    assert frames_on_map().count(('objective', None)) == 2
    # mission data unreadable: no tint, the map still runs
    saved = pc.MissionPlaythroughData
    del pc.MissionPlaythroughData
    KEYBINDS['Refresh map markers'](); step(); step()
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
    KEYBINDS['Refresh map markers']()
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
        close(m9.get('_xscale'), 0.698 * 100, 1e-6)               # Enhanced's scale, without the shear
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
    _io = io
    console_lines = []
    pc.Player = Struct(ViewportClient=Struct(ViewportConsole=Struct(OutputText=console_lines.append)))
    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf):
        KEYBINDS['Minimap diagnostics']()
    diag = buf.getvalue()
    assert console_lines == ['[Classic Minimap] Diagnostic snapshot written to Binaries/Plugins/unrealsdk.log.']
    assert 'diagnostics:' in diag and "'version': '%s'" % mod.__version__ in diag, diag[:300]
    for field in ('dock_mode', 'radar_active', 'givers', 'giver_icons', 'zoom', 'icon_scale', 'echo_x0', 'hud_movie',
                  'hud_fixes'):
        assert "'%s'" % field in diag, field
    # PLAN_V13 decision 8: F7 says which art is in use and where the inputs came from
    assert "'art': 'original'" in diag and 'GfxHUD.upk' in diag and "'enhanced_folder': None" in diag, diag[-600:]
    assert mod.opt_angel_position.value == 'Centered', 'Angel is centred by default (v0.14.7)'
    # v0.16.0: the research into Angel's video and the autosave icon is finished (runs 23-41), so its hooks, watches,
    # log lines and F7 fields are gone: the log stays small, and an ECHO call or a save runs no code of ours.
    for name in ('WillowPlayerController:PlayVoGEchoCall', 'WillowPlayerController:Behavior_PlayEchoCall',
                 'WillowPlayerController:ClientPlayEchoCall', 'WillowHUDGFxMovie:PlayEchoCall',
                 'WillowPlayerController:SetUpVoGScreenParticle', 'WillowPlayerController:ShowScreenParticle:post',
                 'WillowHUD:NotifySavingStarted', 'WillowHUD:NotifySavingComplete'):
        assert 'WillowGame.' + name not in HOOKS, name
    for field in ('angel', 'vog', 'screen_particles', 'save_indicator'):
        assert "'%s'" % field not in diag, field
    # Runs 29-30: Cooked start locations have no Distribution object, only the baked lookup table: [min in, time scale,
    # then LookupTableChunkSize floats per entry] (X forward, Y right, Z up in the camera-aligned local space)
    table = [0.0, 0.01, 0.01, 0.0, 0.0, 0.01, 0.0, 0.0]                 # run 28's VoG table: (0.01, 0, 0) twice
    location = Struct(_type='ParticleModuleLocation', StartLocation=Struct(
        Distribution=None, Type=0, Op=1, LookupTableNumElements=1, LookupTableChunkSize=3, LookupTable=table))
    size = Struct(_type='ParticleModuleSize', StartSize=Struct(Distribution=None, LookupTableChunkSize=3,
                                                               LookupTable=[0.0, 17.76, 17.76, 10.0, 0.0, 17.76,
                                                                            10.0, 0.0]))     # run 29: 17.76 x 10
    emitter = Struct(EmitterName='VoG_Screen', LODLevels=[Struct(Modules=[location, size], RequiredModule=None)])
    template = Obj(Emitters=[emitter], _name="ParticleSystem'fx_PostProcess.VoG.part_VoG_Pulse'")
    # Runs 29-30: the VoG particle is a 17.76 x 10 overlay (local space, X forward, Y right, Z up) that classic shows top
    # right; Angel is centred in every video frame. "Angel position" = Centered (the default) shifts the overlay left
    # by 0.28 of its width (Y start location) before the effect starts (PRE ShowScreenParticle): 0.25 moved her from
    # about 75% to 53% across in run 30, so 0.28 puts her top centre. Classic puts the authored values back. Other
    # effects are left alone.
    show_pre = HOOKS['WillowGame.WillowPlayerController:ShowScreenParticle:pre']
    mod.opt_angel_position.value = 'Centered'
    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf):
        show_pre(pc, Struct(Template=template), None, None)
        show_pre(pc, Struct(Template=template), None, None)            # idempotent
    assert table == [0.0, 0.01, 0.01, -4.97, 0.0, 0.01, -4.97, 0.0], table
    assert buf.getvalue().count("Angel's video moved left by 4.97") == 1, buf.getvalue()
    assert 'start location' not in buf.getvalue(), buf.getvalue()
    other_table = [0.0, 0.0, 0.0, 30.0, 0.0]
    other = Obj(_name="ParticleSystem'fx_PostProcess.Burn'", Emitters=[Struct(EmitterName='Burn', LODLevels=[Struct(RequiredModule=None, Modules=[Struct(
        _type='ParticleModuleLocation', StartLocation=Struct(Distribution=None, LookupTableChunkSize=3,
                                                             LookupTable=other_table))])])])
    with contextlib.redirect_stdout(io.StringIO()):
        show_pre(pc, Struct(Template=other), None, None)
    assert other_table == [0.0, 0.0, 0.0, 30.0, 0.0], 'only the VoG template is changed'
    wide = [0.0, 0.0, 0.0, 90.0, 40.0, 0.0, 100.0, 50.0]                 # random range: min XYZ, max XYZ
    rng = Obj(Emitters=[Struct(EmitterName='Main_VOG', LODLevels=[Struct(RequiredModule=None, Modules=[Struct(
        _type='ParticleModuleLocation', StartLocation=Struct(Distribution=None, LookupTableChunkSize=6,
                                                             LookupTable=wide))])])], _name="ParticleSystem'VoG_Range'")
    with contextlib.redirect_stdout(io.StringIO()):
        show_pre(pc, Struct(Template=rng), None, None)
    assert wide == [0.0, 0.0, 0.0, 85.03, 40.0, 0.0, 95.03, 50.0], wide   # no size module: Main_VOG's 17.76
    mod.opt_angel_position.value = 'Classic'
    with contextlib.redirect_stdout(io.StringIO()):
        show_pre(pc, Struct(Template=template), None, None)
    assert table == [0.0, 0.01, 0.01, 0.0, 0.0, 0.01, 0.0, 0.0], 'Classic restores the authored offset'
    hud = pc.myHUD
    hud.SaveStartTime, hud.SaveDuration, hud.SavingMaterialScale = 131.25, 1.5, 0.5
    hud.SavingMat = "MaterialInstanceConstant'HUD.Materials.SavingIndicator_INST'"
    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf):
        step(0.3)
    assert 'save ' not in buf.getvalue().replace('native save icon', ''), buf.getvalue()    # a save logs nothing
    # PLAN_V15 step 2 (runs 34-35): our own vector Vault logo replaces the native icon while the map is docked. The
    # native one is hidden with SavingMaterialScale 0 (restored when the map isn't docked, and on disable). Ours
    # shows while a save does (SaveDuration > 0), 68 px, beside the map. Its alpha follows the native material on
    # the engine's real-time clock:
    # 100 x clamp(1 - sin(2 pi t), 0, 1), with t = WorldInfo.RealTimeSeconds.
    assert hud.SavingMaterialScale == 0.0, 'map docked and shown: the native icon is hidden'
    save = movie2.root.get('mmsave')
    assert isinstance(save, asvm.Clip) and save.get('_visible') is True, 'SaveDuration 1.5 > 0: shown'
    # Run 38: the native's offset from the ECHO panel left ours about 85 px from the map, for no reason of its own.
    # Ours now sits beside the map's frame: the docked map matrix (0.698, 0.049, 0, 0.700) at p1 + (919.4, 73.4)
    # puts the frame's top-left corner (window -103.95, -86.8 less the 5 px margin) at stage (1059.45, 34.20); the
    # ring ends SAVE_GAP 16 px left of it (8 px left it touching the north marker, run 39), its top level with the
    # frame's. Run 38 measurements (2000 px screenshots, 1.5625 per stage px): the native ring is ~99.5 px across
    # (63.7 stage px), ours at 64 px was ~93.5 (60). Ours is now 68 px (68/128 = 53.125%), ring radius
    # 60 x 68/128 = 31.875: centre (1059.45 - 16 - 31.875, 34.20 + 31.875) = (1011.575, 66.075).
    close(save.get('_x'), 1011.575, 0.06); close(save.get('_y'), 66.075, 0.06)
    close(save.get('_xscale'), 53.125); close(save.get('_yscale'), 53.125)
    for t, alpha in ((10.25, 0.0), (10.75, 100.0), (10.0, 100.0), (10.125, 29.3)):
        pc.WorldInfo.RealTimeSeconds = t
        with contextlib.redirect_stdout(io.StringIO()):
            step(mod.TICK_INTERVAL + 0.01)
        close(save.get('_alpha'), alpha, 0.1)
    hud.SaveDuration = 0.0
    with contextlib.redirect_stdout(io.StringIO()):
        step(0.3)
    assert save.get('_visible') is False and hud.SavingMaterialScale == 0.0, 'save over: ours hidden, native stays off'
    # Run 37: a save during the travel tunnel showed the native icon at its usual spot (the map hides there). The
    # icon stays ours whether or not the map shows (the HUD movie draws over the tunnel, run 7): the native one
    # stays hidden while the mod runs and ours shows beside the map's place.
    hud.SaveDuration = 3.0
    for hide, unhide in ((lambda: setattr(pc, 'loading_movie', True), lambda: setattr(pc, 'loading_movie', False)),
                         (lambda: setattr(hud, 'bShowHUD', False), lambda: setattr(hud, 'bShowHUD', True))):
        hide()
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            step(0.3)
        assert 'minimap hidden' in buf.getvalue(), buf.getvalue()
        assert save.get('_visible') is True and hud.SavingMaterialScale == 0.0, 'map hidden: still ours, native off'
        assert 'native save icon restored' not in buf.getvalue(), buf.getvalue()
        unhide()
        with contextlib.redirect_stdout(io.StringIO()):
            step(mod.SETTLE_SECONDS); step(0.3)
        assert save.get('_visible') is True and hud.SavingMaterialScale == 0.0
    with contextlib.redirect_stdout(buf):
        KEYBINDS['Minimap diagnostics']()
    assert "'save_icon': {'shown': True, 'spot': (1011." in buf.getvalue(), buf.getvalue()[-400:]
    assert "'native_scale': 0.5" in buf.getvalue()
    del hud.SaveStartTime, hud.SaveDuration, hud.SavingMat
    with contextlib.redirect_stdout(io.StringIO()):                    # a HUD without the fields: no crash
        step(0.3)
        KEYBINDS['Minimap diagnostics']()
    # Feedback is optional when there is no viewport console; the diagnostic still reaches the log.
    console = pc.Player.ViewportClient.ViewportConsole
    pc.Player.ViewportClient.ViewportConsole = None
    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf):
        KEYBINDS['Minimap diagnostics']()
        KEYBINDS['Minimap diagnostics']()
    assert buf.getvalue().count('diagnostics:') == 2
    assert buf.getvalue().count('diagnostic console feedback unavailable') == 1
    pc.Player.ViewportClient.ViewportConsole = console
    get_local_pc = mod.get_pc
    mod.get_pc = lambda: None
    try:
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            KEYBINDS['Minimap diagnostics']()
        assert 'diagnostics:' in buf.getvalue()
    finally:
        mod.get_pc = get_local_pc
    mod.on_disable()
    assert movie2.root.get('map') is UNDEF and p1d.get('bearing').get('_visible') is True
    assert pc.myHUD.SavingMaterialScale == 0.5, 'disable gives the native save icon back'
    del pc.myHUD.SavingMaterialScale
    close(p1d.get('echo').get('_x'), 791.5); close(p1d.get('check1').get('_xscale'), 100.04)
    assert TEMPLATE.MovieInfo is STOCK_INFO, 'disable must restore the stock HUD movie'
    # PLAN_V10 worked examples through the real tick hook, using recorded Arid geometry.
    mod.on_enable()
    mod.opt_zoom.value = '100%'
    pc.Pawn.Location = vec(0, 0, 0)
    for slot in slots:
        slot.WaypointLocation = vec(0, 0, 0)
    slots[0].WaypointLocation = vec(6000, 9000, 0)
    pc.myHUD = HUD(Movie(gfx))
    step(); step()
    fitted_art = pc.myHUD.movie.vm.lookup({}, 'map.maps.themap')
    close(fitted_art.get('_xscale'), 185.27, 0.02)
    # Changing objectives refreshes markers but preserves the HUD's fitted zoom.
    slots[0].WaypointLocation = vec(2000, 3000, 0)
    step(0.6)
    close(fitted_art.get('_xscale'), 185.27, 0.02)
    # PLAN_V14: "Zoom mode" Enhanced (default) keeps the HUD's fit like Enhanced does: closing the status menu, where
    # missions are switched, rebuilds the markers only (RebuildMinimapObjects), and a new tracked mission keeps it too
    assert mod.opt_zoom_mode.value == 'Enhanced'
    slots[0].WaypointLocation = vec(20000, 30000, 0)       # far: a refit would give 108%
    HOOKS['WillowGame.StatusMenuExGFxMovie:OnClose'](None, None, None, None)
    step(); step(0.6)
    close(fitted_art.get('_xscale'), 185.27, 0.02)
    tracker.ActiveMission = mission_b
    step(0.6); step()
    close(fitted_art.get('_xscale'), 185.27, 0.02)
    # Objective mode refits when the tracked mission or its status changes, not when a waypoint moves within it
    mod.opt_zoom_mode.value = 'Objective'
    tracker.ActiveMission = mission_a
    step(0.6); step()
    close(fitted_art.get('_xscale'), 108, 0.02)
    slots[0].WaypointLocation = vec(6000, 9000, 0)
    step(0.6); step()
    close(fitted_art.get('_xscale'), 108, 0.02)
    status_a.Status = 2                                    # ready to hand in: a status change refits
    step(0.6); step()
    close(fitted_art.get('_xscale'), 185.27, 0.02)
    mod.opt_zoom_mode.value = 'Enhanced'
    status_a.Status = 1
    slots[0].WaypointLocation = vec(2000, 3000, 0)
    step(0.6); step()
    close(fitted_art.get('_xscale'), 185.27, 0.02)
    # F8 ("Refresh map markers") refits in either mode
    KEYBINDS['Refresh map markers']()
    step()
    close(fitted_art.get('_xscale'), 400)
    assert mod.opt_rebuild.identifier == 'Refresh map markers'
    # v0.16.0: the menu is grouped; each option appears once, and the keybind and the button share one name
    menu = [(type(o).__name__, o.identifier, [c.identifier for c in getattr(o, 'children', ())])
            for o in mod.mod.options]
    assert menu == [
        ('GroupedOption', 'Map', ['Docked size (%)', 'Zoom', 'Zoom mode', 'Icon size (%)', 'Rotate with player']),
        ('GroupedOption', 'Markers', ['Show enemies', 'Enemy range (m)', 'Show mission givers',
                                      'Tint objective diamonds']),
        ('GroupedOption', 'HUD', ['Hide compass', 'Angel position']),
        ('NestedOption', 'Custom position', ['Position', 'Size (%)', 'Right margin', 'Top margin']),
        ('NestedOption', 'Advanced', ['Use Enhanced artwork', 'Refresh map markers',
                                      'Rebuild HUD movie from game files']),
        ('HiddenOption', 'Enhanced folder', [])], menu             # top level, where the README says to set it
    in_menu = [c for o in mod.mod.options for c in getattr(o, 'children', [o])]
    module_options = [v for k, v in vars(mod).items() if k.startswith('opt_')]
    assert sorted(o.identifier for o in in_menu) == sorted(o.identifier for o in module_options)
    assert not hasattr(mod, 'opt_rotation_offset')
    assert sorted(KEYBINDS) == ['Minimap diagnostics', 'Refresh map markers'], sorted(KEYBINDS)
    assert not any('centre' in o.description or 'colour' in o.description
                   for o in in_menu if hasattr(o, 'description')), 'American spelling'
    assert mod.opt_rebuild_movie.identifier == 'Rebuild HUD movie from game files'
    for offset, expected in ((None, 108), ((20000, 30000, 0), 108), ((6000, 9000, 0), 185.27)):
        slots[0].WaypointLocation = vec(*offset) if offset else vec(0, 0, 0)
        KEYBINDS['Refresh map markers']()
        step()
        close(fitted_art.get('_xscale'), expected, 0.02)
    # The multiplier changes the displayed zoom without changing the captured fit.
    mod.opt_zoom.value = '150%'
    mod.opt_zoom.on_change_while_enabled()
    step()
    close(fitted_art.get('_xscale'), 277.9027, 0.02)
    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf):
        KEYBINDS['Minimap diagnostics']()
    assert "'zoom_fit':" in buf.getvalue(), 'F7 must explain the captured zoom'
    assert "'fitted': 185.268" in buf.getvalue() and "'final': 277.902" in buf.getvalue()
    # A different anchor in the same frame also refits (not just a new HUD movie).
    mod.opt_zoom.value = '100%'
    slots[0].WaypointLocation = vec(2000, 3000, 0)
    old_location = FakeAnchor.Location
    try:
        FakeAnchor.Location = vec(100, 200, 0)
        step(0.6)
        close(fitted_art.get('_xscale'), 400)
    finally:
        FakeAnchor.Location = old_location
    # The native gates waypoint collection on RadarMgr; the pawn alone uses 108%.
    world.GRI.RadarMgr = None
    KEYBINDS['Refresh map markers']()
    step()
    close(fitted_art.get('_xscale'), 108)
    world.GRI.RadarMgr = radar
    # Collection can run without a pawn; one waypoint is still fewer than two points.
    pawn = pc.Pawn
    pc.Pawn = None
    try:
        mod.S.fit_anchor = None
        assert mod.collect(pc, pc.myHUD.movie) and mod.capture(pc.myHUD.movie)
        close(fitted_art.get('_xscale'), 108)
    finally:
        pc.Pawn = pawn
    # Run 15: after a level change the capture ran while the pawn still had its previous zone's location
    # (Tartarus coordinates in Arid), so the fit used a wrong player point (108% instead of 400%). Enhanced
    # fits at HUD init, after loading; the mod refits once when the map is first shown after a capture.
    slots[0].WaypointLocation = vec(2000, 3000, 0)
    pc.Pawn.Location = vec(-20000.0, -30000.0, 0.0)       # stale: far from the objective
    pc.loading_movie = True
    pc.myHUD = HUD(Movie(gfx))
    step(); step()
    assert mod.S.phase == 'running' and pc.myHUD.movie.root.get('map').get('_visible') is False
    stale_art = pc.myHUD.movie.vm.lookup({}, 'map.maps.themap')
    close(stale_art.get('_xscale'), 108)                  # fitted from the stale point while hidden
    pc.Pawn.Location = vec(0.0, 0.0, 0.0)                 # the game places the pawn, loading ends
    pc.loading_movie = False
    for _ in range(6):
        step(1.0)
    assert pc.myHUD.movie.root.get('map').get('_visible') is True
    close(stale_art.get('_xscale'), 400)
    assert mod.S.fit_points[0] == (0.0, 0.0, 0.0)
    step(0.6); step()
    close(stale_art.get('_xscale'), 400)                  # refits once, not on every later tick
    # Run 14: T-Bone Junction (DLC3) -> Tartarus Station (DLC4) kept the same HUD, so the mod rebuilt in place.
    # Both use the dlcmap1 frame; the map must leave it so InitMapFrame re-enters it and loads the new DLC movie.
    dlc3, dlc4 = "GFxMovieInfo'dlc3_maps.dlcmap_HUB'", "GFxMovieInfo'dlc4_maps.dlcmap_dlc4tartarus'"
    saved_anchor = (FakeAnchor.MapFrame, FakeAnchor.DLCMap, WORLD.zone_frame)
    try:
        FakeAnchor.MapFrame, FakeAnchor.DLCMap, WORLD.zone_frame = 'dlcmap1', dlc3, 'dlcmap1'
        WORLD.loaded_dlc = None
        mod.rebuild()
        step(); step(); step()
        assert WORLD.loaded_dlc == dlc3 and mod.S.anchor['DLCMap'] == dlc3, (WORLD.loaded_dlc, mod.S.phase)
        FakeAnchor.DLCMap = dlc4                       # same frame label, new DLC package
        mod.rebuild()
        step(); step(); step()
        assert WORLD.loaded_dlc == dlc4, 'the DLC4 movie must replace the DLC3 one: %r' % WORLD.loaded_dlc
        assert mod.S.phase == 'running' and mod.S.anchor['DLCMap'] == dlc4
        WORLD.loaded_dlc = None
        mod.rebuild()                                  # same DLC again: no reload (no blank map in between)
        step(); step()
        assert WORLD.loaded_dlc is None and mod.S.phase == 'running'
    finally:
        FakeAnchor.MapFrame, FakeAnchor.DLCMap, WORLD.zone_frame = saved_anchor
    # A movie already merged with another mod's HUD (the local-only Extended UI check) carries no block
    # manifest, so the merge scenarios below can't run on it; everything above still did.
    if any(c == swfmerge.METADATA for c, _, _ in swfmerge.split(gfx)[1]):
        # PLAN_V12: another HUD mod (Extended UI) replaces the template's movie after our redirect. We merge our
        # block into its movie at runtime instead of fighting for the template (ADR 0003: never override).
        mod.on_disable()
        OBJECTS['GfxHUD.FlashMovie.HUD'] = STOCK_INFO
        TEMPLATE.MovieInfo = STOCK_INFO
        mod.on_enable()
        assert TEMPLATE.MovieInfo is MINIMAP_INFO
        foreign_bytes = foreign_from(gfx)
        foreign = Struct(name="GFxMovieInfo'GfxHUD_MOD.FlashMovie.HUD'", RawData=foreign_bytes, Outer='GfxHUD_MOD',
                         texture_refs=['their textures'])
        expected = swfmerge.merge(foreign_bytes, gfx, mod.__version__)
        constructed_before = len(MOVIE_INFOS)
        console_lines.clear()
        hook_menu = HOOKS['Engine.WorldInfo:IsMenuLevel']

        # 1. their patch() runs first (PRE), then our POST hook merges into their movie
        TEMPLATE.MovieInfo = foreign
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            hook_menu(None, None, None, None)
        merged = TEMPLATE.MovieInfo
        assert merged is not foreign and merged is not MINIMAP_INFO and MOVIE_INFOS[-1] is merged
        assert len(MOVIE_INFOS) == constructed_before + 1
        assert merged.RawData == list(expected) or bytes(merged.RawData) == expected, 'merged movie bytes'
        assert merged.ObjectFlags & KEEP_ALIVE, 'objects constructed from Python must be KEEP_ALIVE (fact 3)'
        assert merged.texture_refs == foreign.texture_refs, 'the merged info keeps their properties'
        assert mod.Redirect.original is foreign and mod.Redirect.template is TEMPLATE
        status = mod.Redirect.status
        assert 'Merged' in status and 'next level load' in status, status
        assert status in buf.getvalue(), 'the status reaches the SDK log'
        assert console_lines == ['[Classic Minimap] ' + status], console_lines
        assert status in mod.mod.description and mod.BASE_DESCRIPTION in mod.mod.description
        # Timing is logged (decision 6), split into its phases: in game the total was about 1 s more than
        # the parts measured in run 18, so the log has to say where it goes (PHASE3 3bo).
        timing = re.search(r'merged in (\d+\.\d\d)s \(read (\d+\.\d\d)s, merge (\d+\.\d\d)s, '
                           r'write (\d+\.\d\d)s; (\d+) bytes\)', buf.getvalue())
        assert timing, buf.getvalue()
        assert int(timing[5]) == len(expected)

        # 2. already merged: the hook returns at once, nothing is constructed
        hook_menu(None, None, None, None)
        assert TEMPLATE.MovieInfo is merged and len(MOVIE_INFOS) == constructed_before + 1

        # 3. a HUD that spawned before the merge keeps their movie: idle with an honest message; the next one runs
        spawned = Movie(gfx, patched=False, info=foreign)
        pc.myHUD = HUD(spawned)
        mod.S.reset()
        step(); step()
        assert mod.S.phase == 'stockhud' and spawned.invokes == []
        next_level = Movie(gfx, info=merged)
        pc.myHUD = HUD(next_level)
        mod.S.reset()
        WORLD.anchor_loaded = True
        for _ in range(3):
            step(0.6)
        assert isinstance(next_level.root.get('map'), asvm.Clip) and mod.S.phase in ('framewait', 'running')

        # 4. disable restores their movie, only while the template still points at the merged object
        mod.on_disable()
        assert TEMPLATE.MovieInfo is foreign
        mod.on_enable()                                        # same session, same foreign movie: reuse the merge
        assert TEMPLATE.MovieInfo is merged and len(MOVIE_INFOS) == constructed_before + 1
        other = Struct(name="GFxMovieInfo'Other.FlashMovie.HUD'", RawData=b'')
        TEMPLATE.MovieInfo = other                             # someone else took the template after us
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            mod.on_disable()
        assert TEMPLATE.MovieInfo is other and 'left the template alone' in buf.getvalue()

        # 5. enabled after their mod: the template already holds their movie
        TEMPLATE.MovieInfo = foreign
        mod.on_enable()
        assert TEMPLATE.MovieInfo is merged and len(MOVIE_INFOS) == constructed_before + 1
        mod.on_disable()
        assert TEMPLATE.MovieInfo is foreign

        # 6. a changed foreign movie (their update) is merged afresh, not served from the old merge
        foreign2 = Struct(name="GFxMovieInfo'GfxHUD_MOD.FlashMovie.HUD2'", RawData=foreign_from(gfx, 5001), Outer='x')
        TEMPLATE.MovieInfo = foreign2
        mod.on_enable()
        assert TEMPLATE.MovieInfo is not merged and TEMPLATE.MovieInfo is MOVIE_INFOS[-1]
        assert len(MOVIE_INFOS) == constructed_before + 2
        mod.on_disable()
        assert TEMPLATE.MovieInfo is foreign2

        # 7. refusals: the template keeps their movie, nothing is constructed, the message says why
        block_id = swfmerge.read_block(gfx)[0]['characters'][0]
        for label, bad_bytes, why in (
                ('id clash', foreign_from(gfx, block_id), 'character id clash at %d' % block_id),
                ('prefix', foreign_from(gfx, prefix_tag=True), 'differs from the stock'),
                ('unreadable', b'CWS' + foreign_from(gfx)[3:], 'unsupported movie signature')):
            bad = Struct(name="GFxMovieInfo'Bad.%s'" % label, RawData=bad_bytes, Outer='x')
            TEMPLATE.MovieInfo = bad
            count = len(MOVIE_INFOS)
            console_lines.clear()
            mod.on_enable()
            assert TEMPLATE.MovieInfo is bad and len(MOVIE_INFOS) == count, label
            assert mod.Redirect.status.startswith('Refused: ') and why in mod.Redirect.status, (label, mod.Redirect.status)
            assert console_lines == ['[Classic Minimap] ' + mod.Redirect.status]
            assert mod.Redirect.status in mod.mod.description
            hook_menu(None, None, None, None)                   # asked again: still refused, status line not duplicated
            assert TEMPLATE.MovieInfo is bad
            mod.on_disable()
            assert TEMPLATE.MovieInfo is bad, 'a refused movie was never ours to restore'
        # a refused HUD leaves the minimap idle, with a message that is not the old "load a save" hint
        pc.myHUD = HUD(Movie(gfx, patched=False, info=bad))
        mod.on_enable()
        mod.S.reset()
        step(); step()
        assert mod.S.phase == 'stockhud'

        # 8. a movie built for another mod version is a refusal that says to rebuild it
        TEMPLATE.MovieInfo = foreign
        real_version = mod.__version__
        mod.__version__ = '0.0.1'
        try:
            mod.on_enable()
            assert TEMPLATE.MovieInfo is foreign and 'Rebuild HUD movie' in mod.Redirect.status, mod.Redirect.status
        finally:
            mod.__version__ = real_version
        mod.on_disable()

        # 9. nothing foreign: the stock path is unchanged
        TEMPLATE.MovieInfo = STOCK_INFO
        mod.on_enable()
        assert TEMPLATE.MovieInfo is MINIMAP_INFO and not mod.Redirect.status.startswith('Refused')
        hook_menu(None, None, None, None)
        assert TEMPLATE.MovieInfo is MINIMAP_INFO
    else:
        print('no block manifest in this movie: skipped the runtime merge scenarios')
    mod.on_disable()
    print('all minimap mod integration checks passed')


if __name__ == '__main__':
    main(sys.argv[1])
