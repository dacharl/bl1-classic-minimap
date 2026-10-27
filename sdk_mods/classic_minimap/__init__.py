"""Classic Minimap: an Enhanced-style minimap for Borderlands GOTY (classic, x86).

Doc citations below (PHASE3 3f, PLAN_V08 3, ENHANCED_NATIVE.md 4, ...) refer to files under docs/; start at
docs/PROGRESS.md.

The HUD movie is player-built (PLAN_V13, ADR 0004): on enable, hudmovie.py builds the stock HUD movie plus
the `bl1mm_map` clip and the root functions this mod calls from the player's own GfxHUD.upk and
menus_ingame_redux.upk (and Enhanced's GfxHUD.upk for its art, when installed), or reads it from the movie
cache. No game files ship with the mod.

Why the template: classic WillowGame.u carries its own cooked copy of GfxHUD.FlashMovie.HUD and the
hud_instance template, loaded at startup, so GfxHUD.upk on disk is never read (PHASE3.md 3d). On enable the
mod constructs a GFxMovieInfo holding the built movie and points the template's MovieInfo at it; HUDs
spawned afterwards (any level load) use it. Disable restores the original.

How it works (ENHANCED_NATIVE.md; PLAN_DIRECT.md step B):
  * per HUD / mission / area: a WillowGFxHelperMap is constructed and released within one call. Init runs
    classic's own object collectors (script FindLandmarks, native FindObjects/FindPlayers) and native
    InitMapFrame selects the zone frame (or DLC movie). The anchor's fields and every object's world
    position are copied as plain Python values; nothing native is held between ticks;
  * once the zone frame is on stage, Transform and CoordScale are computed in Python exactly as the native
    does (anchor matrix: rotation x TextureSize*DrawScale3D*DrawScale, translated to Location, inverted;
    verified against the helper's own Transform to 6.5e-8) and every landmark is projected;
  * every PlayerTick (20 Hz): the pawn is projected
    (tr.x = (v + 0.5) * CoordScale.X, tr.y = (0.5 - u) * CoordScale.Y, (u, v) = [x y z 1] * Transform)
    and sent with its heading to the movie, which places the player icon and centres/rotates the map;
  * enemy dots: WillowGameReplicationInfo.RadarMgr.RemoteDynamicIcons (active entries), the list the
    compass radar draws and Enhanced's UpdateThreats reads; a pawn scan is the fallback;
  * objective slots take Enhanced's icon type from the tracked mission's status (turn-in mark, "!", or the
    diamond; PHASE3 3ak), or with "Tint objective diamonds" the diamond tinted gold/green;
  * docked like Enhanced (PLAN_V07.md 3): the map takes Enhanced's p1-space placement, sheared like the other
    right-column HUD elements (transform.matrix, with an unsheared fallback), and while it shows, ECHO, the
    mission title and the checklist move to Enhanced's positions (its p<N>.UpdateEchoPosition);
  * rebuilds (mission/objective/area changes) swap the markers in place, without hiding the map;
  * Enhanced's minimap box: the map clip is laid out like Enhanced's (its box art, its 207.95 x 173.65
    window), so docking and icon size use Enhanced's units (PLAN_V09); zoom fits the player and
    objectives at capture, as Enhanced's QuickAccessInit does (PLAN_V10);
  * edge indicators for north and off-window
    objectives, and mission givers: "!" where classic's own GetEligibleMissions says a mission can start,
    the turn-in icon where GetRedeemableMissions says one can be handed in (PLAN_V08.md).
"""
import json
import math
import time
from pathlib import Path
from typing import Any

import unrealsdk
from mods_base import (SETTINGS_DIR, BoolOption, ButtonOption, HiddenOption, ObjectFlags, SliderOption, SpinnerOption,
                       build_mod, get_pc, hook, keybind)
from unrealsdk.hooks import Type
from unrealsdk.unreal import WeakPointer

from . import hudmovie
from .swfmerge import MergeRefused
from .swfmerge import merge as merge_movie

__version__ = "0.14.8"


STAGE_W = 1280.0                       # classic HUD stage is 1280x720
# The map clip is laid out like Enhanced's minimap clip (E_HUD sprite 187, PLAN_V09): its window (E shape 82,
# 207.95 x 173.65) centred on the clip origin, its box art behind. Docking, zoom and icons are therefore in
# Enhanced's own units.
MASK_LEFT, MASK_TOP, MASK_W, MASK_H = -103.95, -86.8, 207.95, 173.65
MASK_RIGHT = MASK_LEFT + MASK_W
CUSTOM_REF_W = 820.75                  # Custom position: window width in px at Size 100% (pre-v0.9 meaning)
DOCK_CHECK_INTERVAL = 1.0              # re-dock when p1 moves or a layout switch replaces it
LAYOUT_MATCH = 2.0                     # p1.echo authored _x tolerance for identifying the layout
CHECK_SCALE = (92.02, 92.0)            # Enhanced check<n> matrix (0.918, 0.064 / 0.920) as _xscale/_yscale
# Enhanced p1 placements per HUD layout (E_HUD sprites 933 = 16:9, 949 = 4:3; tools/swftimeline.py), keyed by
# classic's authored p1.echo _x in the matching layout sprite (706 = 16:9, 722 = 4:3).
LAYOUTS = {
    "16:9": {"echo0": 791.5, "map": (0.698, 0.049, 0.0, 0.700, 919.4, 73.4), "echo": (610.0, 13.1),
             "quest": (577.0, 129.1), "check": (795.9, 59.4, 16.4)},
    "4:3": {"echo0": 655.5, "map": (0.698, 0.049, 0.0, 0.700, 708.4, 99.4), "echo": (615.5, 26.1),
            "quest": (377.9, 180.1), "check": (596.8, 109.0, 16.4)},
}
TICK_INTERVAL = 0.05                   # 20 Hz, like Enhanced's HUD scheduler interval
THREAT_INTERVAL = 0.25
OBJECTIVE_CHECK_INTERVAL = 0.5         # mission/area change check (Objective Distance caches on the same key)
EPOCH_CHECK_INTERVAL = 0.25            # live-level set check for the settle rule
WAYPOINT_GRID = 100.0                  # objective-position rounding (Unreal units, ~2 m) for the rebuild key
SETTLE_SECONDS = 3.0                   # steam-deck-scripts specs: start after 3 s of stable ready context
READY_TIMEOUT = 5.0                    # seconds to wait for the zone frame before re-initialising
RETRY_INTERVAL = 1.0                   # MinimapCreate retry spacing while the HUD movie comes up
MAX_ATTEMPTS = 60
# Enhanced's no-objective zoom: ApplyScale(100), QuickAccessInit's optional fit, then AnalogScale(+8).
# With objectives, fit_zoom reproduces the native's 100..400 clamp (PLAN_V10 research 1).
ENH_ZOOM = 108.0
ZOOM_CHOICES = ["50%", "75%", "100%", "125%", "150%", "200%"]
ANCHOR_RETRY = 1.0                     # no anchor yet (level still streaming): retry spacing...
ANCHOR_RETRY_SLOW = 5.0                # ...and after 10 tries (areas without a map)
UU_PER_M = 50.0                        # 1 m ~ 50 Unreal units
PAWN_FALLBACK_RANGE_M = 100.0          # pawn-scan fallback range when "Enemy range" is 0 (no limit)
RADAR_PROBE_RANGE_UU = 1500.0          # an enemy this close should be on the radar...
RADAR_MISS_LIMIT = 5                   # ...if it isn't on this many probes, switch to the pawn scan
RADAR_PROBE_EVERY = 8                  # probe every Nth empty radar read (THREAT_INTERVAL each)
MS_NOT_STARTED, MS_READY_TO_TURN_IN = 0, 2     # IMission.EMissionStatus
STATUS_FRAME = {MS_NOT_STARTED: "newmission", MS_READY_TO_TURN_IN: "turnin"}   # Enhanced's objective icon types
STATUS_TINT = {MS_NOT_STARTED: 0x50E050, MS_READY_TO_TURN_IN: 0xFFC420}   # "Tint objective diamonds" (v0.6 style)
VOG_WATCH_SECONDS = 10.0               # after an Angel call: log her screen mesh / particle once a second
VOG_FAST_SECONDS = 15.0                # after an ECHO call: watch the root vog clip every tick (run 24 diagnostic)
VOG_NUMBERS = ("_x", "_y", "_width", "_height", "_xscale", "_yscale", "_alpha", "_currentframe", "_totalframes")
SAVE_FIELDS = ("SaveStartTime", "SaveDuration", "SavingMaterialScale", "SavingMat")   # WillowHUD autosave icon
SAVE_CHECK_INTERVAL = 0.25             # autosave diagnostic: how often to read them (v0.14.8)
GIVER_OBJECTIVE_UU = 500.0             # a giver this close to an objective is its NPC: one mark there (PHASE3 3ak)
LANDMARK_CLIP = "map.maps.landmarks"   # icon template clip (frames objective .. questionmark, turnin, newmission)
RECORD_KINDS = {"FloatProperty", "IntProperty", "BoolProperty", "ByteProperty", "StrProperty", "NameProperty",
                "StructProperty", "ObjectProperty"}
ANCHOR_LOG: Path = SETTINGS_DIR / "classic_minimap_anchors.jsonl"
MOVIE_NAME = "MinimapHUD"              # the GFxMovieInfo constructed from the player-built movie
OLD_PACKAGE = "GfxHUD_Minimap.upk"     # v0.12 and earlier; no longer used (PLAN_V13 decision 7)
STOCK_PATH = "GfxHUD.FlashMovie.HUD"
TEMPLATE_PATH = "GfxHUD.FlashInstances.hud_instance"   # GFxMovieDefinition.Movie for the HUD

opt_position = SpinnerOption("Position", "Docked", ["Docked", "Custom"],
                             description="Docked: where Enhanced puts it, tilted like the HUD, with ECHO and the "
                                         "mission text moved aside. Custom: use the size and margins below.")
opt_dock_size = SliderOption("Docked size (%)", 100, 60, 160, description="Size of the docked minimap.")
opt_scale = SliderOption("Size (%)", 28, 15, 60, description="Custom position: size of the minimap window.")
opt_margin_x = SliderOption("Right margin", 24, 0, 400, description="Custom position: distance from the right edge.")
opt_margin_y = SliderOption("Top margin", 20, 0, 600, description="Custom position: distance from the top.")
opt_zoom = SpinnerOption("Zoom (vs Enhanced)", "100%", ZOOM_CHOICES,
                         description="Map zoom; 100% matches the Enhanced edition's minimap.")
opt_zoom_mode = SpinnerOption("Zoom mode", "Enhanced", ["Enhanced", "Objective"],
                              description="Enhanced: fit the zoom to you and your objectives once per level load, "
                                          "like Enhanced. Objective: also refit when your tracked mission or its "
                                          "status changes. F8 refits in both.")
opt_icon_size = SliderOption("Icon size (%)", 100, 50, 200,
                             description="Landmark, player and enemy icon size; 100% matches Enhanced.")
opt_givers = BoolOption("Show mission givers", True,
                        description="Show ! where a new mission can be picked up and the turn-in icon where "
                                    "a finished mission can be handed in, like Enhanced.")
opt_objective_tint = BoolOption("Tint objective diamonds", False,
                                description="Off (like Enhanced): a mission ready to hand in shows the turn-in mark "
                                            "and one not started shows !, in place of the objective diamond. On: "
                                            "the diamond stays and turns gold (ready to hand in) or green (not "
                                            "started).")
opt_rotate = BoolOption("Rotate with player", False, description="Rotate the map so you always face up.")
opt_rotation_offset = SpinnerOption("Rotation offset", "0", ["0", "90", "180", "270"], is_hidden=True,
                                    description="Correction if the player arrow doesn't point up when rotating.")
opt_threats = BoolOption("Show enemies", True, description="Show enemies the compass radar tracks as red dots.")
opt_threat_range = SliderOption("Enemy range (m)", 0, 0, 200,
                                description="Only show enemies this close. 0 = no limit, like Enhanced.")
opt_hide_compass = BoolOption("Hide compass", False, description="Hide the classic compass strip.")
# PLAN_V13 decision 8: the art choice, a manual Enhanced folder (edit classic_minimap.json; the SDK has no
# text-entry option) and a rebuild; both rebuild the HUD movie, used from the next level load
opt_enhanced_art = BoolOption("Use Enhanced artwork", True,
                              description="Use GOTY Enhanced's minimap artwork when it is installed; off uses the "
                                          "mod's own art. Takes effect from the next level load.",
                              on_change_while_enabled=lambda _, value: remake_movie(use_enhanced=value))
opt_angel_position = SpinnerOption("Angel position", "Centered", ["Classic", "Centered"],
                                   description="Where Angel's ECHO video appears. Centered: top centre, clear of the "
                                               "minimap, like GOTY Enhanced. Classic: top right, partly behind the "
                                               "minimap. Applies from her next call.")
opt_enhanced_folder = HiddenOption("Enhanced folder", "",
                                   description="GOTY Enhanced's game folder, if the mod doesn't find it itself.")


def release(obj: Any) -> None:
    """Let the GC have an object we constructed with KEEP_ALIVE."""
    if obj is not None:
        try:
            obj.ObjectFlags &= ~int(ObjectFlags.KEEP_ALIVE)
        except Exception:
            pass


class State:
    """Per-HUD state.

    Only plain Python values are kept between ticks. The HUD movie is held through a WeakPointer, so a
    movie the engine has destroyed reads as None instead of a dangling object.
    """

    def __init__(self) -> None:
        self._movie: WeakPointer = WeakPointer()
        self.tracker: WeakPointer = WeakPointer()   # survives resets; re-found when it reads None
        self.globals_ref: WeakPointer = WeakPointer()
        # level epoch for the settle rule; survives map rebuilds (a mission change shouldn't hide the map)
        self.epoch: Any = None
        self.epoch_since: Any = None
        self.next_epoch_check = 0.0
        # threat source survives resets: once the radar proved empty, don't re-learn it every rebuild
        self.threat_source = "radar"
        self.radar_empty = 0
        self.radar_misses = 0
        self.reset()
        self.warned: set[str] = set()     # survives resets so warnings print once per session
        self.recorded: set[str] = set()   # anchors already written to ANCHOR_LOG this session
        self.pings = 0

    @property
    def movie(self) -> Any:
        return self._movie()

    @movie.setter
    def movie(self, m: Any) -> None:
        self._movie = WeakPointer(m)

    def reset(self) -> None:
        self.movie = None
        self.phase = "idle"          # idle -> (retry | anchorwait) -> framewait -> running
        self.wait_started = 0.0
        self.next_tick = 0.0
        self.next_threats = 0.0
        self.layout_dirty = False
        self.attempts = 0
        self.retry_at = 0.0
        self.objective_key: Any = None
        self.next_objective_check = 0.0
        self.anchor_attempts = 0
        self.shown: Any = None             # last map._visible we set (None = unknown, set next tick)
        self.last_hidden_reason = "start"
        self.rebuild_pending = False       # rebuild the markers on the next tick...
        self.rebuild_refit = False         # ...and refit the zoom (F8, option changes; not the status menu)
        self.vog_until = 0.0               # Angel-call watch window end (run 23 spike)...
        self.vog_next = 0.0                # ...next check...
        self.vog_last: Any = None          # ...and the mesh translation last seen
        self.vog_clip: Any = ()            # root vog clip state last logged (() = not read yet; run 24 diagnostic)...
        self.vog_clip_next = 0.0           # ...next once-a-second read...
        self.vog_fast_until = 0.0          # ...and the end of the every-tick watch after an ECHO call
        self.sp_until = 0.0                # screen-particle watch window end (run 26 diagnostic)...
        self.sp_next = 0.0                 # ...and its next once-a-second log
        self.save_state: Any = ()          # autosave fields last logged (() = not read yet; v0.14.8 diagnostic)...
        self.save_next = 0.0               # ...and the next read
        self.mission_key: Any = None       # tracked mission and status at the last collect (Objective zoom mode)
        self.fit_mission: Any = None       # ... and at the last fit
        # docking (PLAN_V07 3): layout name when docked, p1 signature it was computed for, HUD column state
        self.dock: Any = None
        self.p1_sig: Any = None
        self.dock_mode: Any = None
        self.hud_on = False
        self.hud_fixes = 0                 # times the movie re-applied the shift after the game undid it
        self.next_dock_check = 0.0
        # copied at collection time (no native references)
        self.anchor: dict[str, Any] = {}
        self.sources: list[tuple[str, str, float, float, float, bool]] = []
        self.tint: Any = None
        self.objective_frame = "objective"
        self.givers: list[Any] = []        # WeakPointers to interactive objects with mission directives
        # computed once the zone frame is on stage
        self.xf: tuple[float, ...] = ()
        self.cs: tuple[float, float] = (1.0, 1.0)
        self.frame = 0.0
        self.marks: list[tuple[str, str, float, float, float, Any]] = []
        self.fit = ENH_ZOOM
        self.fit_raw: Any = None
        self.fit_points: list[tuple[float, float, float]] = []
        self.zoom_points: list[tuple[float, float, float]] = []
        self.fit_anchor: Any = None
        self.fit_art: tuple[float, float] = (0.0, 0.0)     # zone art size at 100%, for refit_when_shown
        self.fit_pending = False
        self.fit_has_pawn = self.zoom_has_pawn = False     # whether the first point is the pawn's


S = State()


def warn_once(key: str, msg: str) -> None:
    if key not in S.warned:
        S.warned.add(key)
        print(f"[Classic Minimap] {msg}")


def fmt(v: Any) -> str:
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        return f"{v:.9g}"      # 9 significant digits: matrix terms like 0.0131 need them, not 6 decimals
    return str(v)


def cmd(movie: Any, op: str, *args: Any) -> None:
    """Run a minimap command in the HUD movie: root MinimapCmd("op~arg~...").

    Never use GFxMovie.Invoke from Python here. Classic doesn't fill in its ASValue return, which holds an
    FString; pyunrealsdk converting that garbage crashed the game (access violation in pyunrealsdk.dll,
    PHASE3 3e). WillowGFxMovie.SingleArgInvokeS is native, takes one string and returns nothing.
    """
    movie.SingleArgInvokeS("MinimapCmd", "~".join([op] + [fmt(a) for a in args]))


def get_str(movie: Any, path: str) -> Any:
    try:
        return movie.GetVariableString(path)
    except Exception as ex:
        return f"<{type(ex).__name__}: {ex}>"


def get_num(movie: Any, path: str) -> Any:
    try:
        return movie.GetVariableNumber(path)
    except Exception as ex:
        return f"<{type(ex).__name__}: {ex}>"


def finite_positive(v: Any) -> bool:
    # GetVariableNumber on a missing GFx path returns Infinity (PHASE0 2b)
    return isinstance(v, float) and math.isfinite(v) and v > 0


def current_hud_movie(pc: Any) -> Any:
    hud = pc.myHUD
    if hud is None:
        return None
    try:
        return hud.GetHUDMovie()
    except Exception:
        return None


def layout(movie: Any) -> bool:
    """Attach/place the map: docked (Enhanced placement, sheared) or at the custom size and margins."""
    x, y, s = custom_placement()
    cmd(movie, "create", x, y, s * 100.0)
    v = get_num(movie, "map._x")          # Infinity when _root.map doesn't exist
    if not (isinstance(v, float) and math.isfinite(v)):
        return False
    dock(movie, x, y, s)
    return True


def custom_placement() -> tuple[float, float, float]:
    """Custom position: (x, y, clip scale) putting the window's top-right corner at the margins, the window
    CUSTOM_REF_W x Size% wide."""
    s = CUSTOM_REF_W * opt_scale.value / 100.0 / MASK_W
    return STAGE_W - opt_margin_x.value - MASK_RIGHT * s, opt_margin_y.value - MASK_TOP * s, s


def p1_signature(movie: Any) -> Any:
    """p1's transform, plus whether it is the instance we recorded (a layout switch places a new p1)."""
    vals = [get_num(movie, "p1." + k) for k in ("_x", "_y", "_xscale", "_yscale")]
    if not all(isinstance(v, float) and math.isfinite(v) for v in vals):
        return None
    return (*(round(v, 2) for v in vals), finite(get_num(movie, "p1.mmOrig.echo_x")))


def finite(v: Any) -> bool:
    return isinstance(v, float) and math.isfinite(v)


def current_layout(movie: Any) -> Any:
    """Record p1's authored column (hud mode 2) and identify the layout from classic's echo placement.
    Unless the shift is meant to be on, restore it too: after a reset the column may still be shifted."""
    hud_cmd(movie, 2, LAYOUTS["16:9"])
    if not S.hud_on:
        hud_cmd(movie, 0, LAYOUTS["16:9"])
    echo0 = get_num(movie, "mmEchoX0")
    if not finite(echo0):
        return None
    for name, lay in LAYOUTS.items():
        if abs(echo0 - lay["echo0"]) <= LAYOUT_MATCH:
            return name
    return None


def dock_matrix(lay: dict[str, Any], p1: tuple[float, ...]) -> tuple[float, ...]:
    """Stage matrix for _root.map: Enhanced's own p1-space placement of its minimap clip (shear included;
    our clip has the same layout, PLAN_V09), scaled about the clip origin by Docked size, then p1's own
    transform (unsheared: x/y + scale)."""
    a, b, c, d, tx, ty = lay["map"]
    k = opt_dock_size.value / 100.0
    la, lb, lc, ld = k * a, k * b, k * c, k * d
    px, py, sx, sy = p1[0], p1[1], p1[2] / 100.0, p1[3] / 100.0
    return sx * la, sy * lb, sx * lc, sy * ld, sx * tx + px, sy * ty + py


def dock(movie: Any, x: float, y: float, s: float) -> None:
    """Docked: Enhanced's placement for the current p1 layout. Custom, or a layout we don't know (split
    screen): the plain size/margin placement, set through the same matrix path so no old shear lingers."""
    S.dock = None
    S.p1_sig = p1_signature(movie)
    name = current_layout(movie) if opt_position.value == "Docked" and S.p1_sig is not None else None
    if opt_position.value == "Docked" and name is None:
        warn_once("nolayout", "unknown HUD layout (split screen?): using the custom position")
    if name is None:
        if S.hud_on:
            hud_shift(movie, False)
        cmd(movie, "dock", s, 0.0, 0.0, s, x, y)
        return
    S.dock = name
    S.p1_sig = p1_signature(movie)        # now includes the recorded originals
    cmd(movie, "dock", *dock_matrix(LAYOUTS[name], S.p1_sig))
    mode = get_str(movie, "mmDockMode")
    if mode != S.dock_mode:
        S.dock_mode = mode
        if mode == "matrix":
            log(f"docked ({name} HUD layout), tilted like the HUD")
        else:
            log(f"docked ({name} HUD layout) without the tilt: this runtime ignored transform.matrix "
                f"(read back b={get_num(movie, 'mmDockB')})")
    if S.hud_on:
        hud_shift(movie, True)            # a new p1 instance (layout switch) has its authored positions back


def hud_cmd(movie: Any, mode: int, lay: dict[str, Any]) -> None:
    ex, ey = lay["echo"]
    qx, qy = lay["quest"]
    cx, cy, cdy = lay["check"]
    cmd(movie, "hud", mode, ex, ey, qx, qy, cx, cy, cdy, *CHECK_SCALE)


def hud_shift(movie: Any, on: bool) -> None:
    """Move ECHO / mission title / checklist to Enhanced's docked positions, or restore them."""
    if on and S.dock is None:
        return
    hud_cmd(movie, 1 if on else 0, LAYOUTS[S.dock or "16:9"])
    S.hud_on = on


def check_dock(movie: Any) -> None:
    """Re-dock when p1 moved, scaled, or was replaced (resolution or HUD layout change)."""
    sig = p1_signature(movie)
    if sig != S.p1_sig:
        dock(movie, *custom_placement())
    fixes = get_num(movie, "mmHudFixes")       # MinimapHudKeep re-applied the shift (run 25)
    if finite(fixes) and fixes > S.hud_fixes:
        S.hud_fixes = int(fixes)
        log(f"the game put the ECHO panel back behind the map; moved it again ({S.hud_fixes} "
            f"time{'s' if S.hud_fixes != 1 else ''})")


def teardown(movie: Any = None) -> None:
    m = movie or S.movie
    if m is not None:
        try:
            if S.hud_on:
                hud_shift(m, False)
            cmd(m, "destroy")
            m.SetVariableBool("p1.bearing._visible", True)
        except Exception:
            pass
    S.reset()


def log(msg: str) -> None:
    print(f"[Classic Minimap] {msg}")


def describe(movie: Any) -> dict[str, Any]:
    """Raw GFx state for the log, read back through side effects (commands return nothing)."""
    S.pings += 1
    token = f"pong{S.pings}"
    try:
        cmd(movie, "ping", token)
    except Exception as ex:
        token = f"<command failed: {type(ex).__name__}: {ex}>"
    return {
        "movie": str(movie),
        "root functions": get_str(movie, "mmPing") == token,  # MinimapPing ran -> patched code is live
        "mmPing": get_str(movie, "mmPing"),
        "mmCreateMode": get_str(movie, "mmCreateMode"),      # attach / fallback / none
        "map._x": get_num(movie, "map._x"),                  # Infinity = no _root.map
        "map.mask._width": get_num(movie, "map.mask._width"),
        "mmfallback._x": get_num(movie, "mmfallback._x"),    # -20000 = timeline fallback present, unused
        "p1._x": get_num(movie, "p1._x"),                    # stock HUD clip, sanity check
    }


class Redirect:
    template: Any = None
    original: Any = None          # what disable restores: the stock movie, or the other mod's movie when merged
    movie_info: Any = None        # the GFxMovieInfo constructed from the player-built movie (PLAN_V13)
    movie_data: Any = None        # the bytes `movie_info` holds; a new build means a new object
    result: Any = None            # hudmovie.Result: the player-built movie and how it was made
    old_noted: bool = False       # the old GfxHUD_Minimap.upk note: once per session
    merged: Any = None            # our block spliced into another mod's movie (PLAN_V12)
    merged_from: Any = None       # the foreign movie `merged` was built from; reused while it is unchanged
    merged_active: bool = False   # the template points at `merged` because of us
    refused: Any = None           # a foreign movie we refused; not re-checked while the template holds it
    enabled: bool = False
    status: str = ""


def find(cls: str, path: str) -> Any:
    try:
        return unrealsdk.find_object(cls, path) or None
    except Exception:
        return None


def console_line(msg: str) -> None:
    """Print to the in-game console (the F7 path); optional, since it needs a viewport."""
    try:
        get_pc().Player.ViewportClient.ViewportConsole.OutputText(f"[Classic Minimap] {msg}")
    except Exception:
        pass


def set_status(msg: str) -> None:
    """Say why the minimap is or isn't running: SDK log, in-game console and the MODS menu (PLAN_V12 decision 5)."""
    if msg == Redirect.status:
        return
    Redirect.status = msg
    log(msg)
    console_line(msg)
    try:
        mod.description = f"{BASE_DESCRIPTION}\n\n{msg}" if BASE_DESCRIPTION else msg
    except Exception:
        pass


def clear_status() -> None:
    Redirect.status = ""
    try:
        mod.description = BASE_DESCRIPTION
    except Exception:
        pass


def is_stock(info: Any) -> bool:
    return STOCK_PATH in str(info)


def player_movie(rebuild: bool = False, use_enhanced: Any = None) -> Any:
    """The player-built movie's bytes (PLAN_V13): built from the game files, or read from the movie cache.

    None, with a status line, when classic's files can't be built from (decision 17)."""
    if Redirect.result is not None and not rebuild and use_enhanced is None:
        return Redirect.result.data
    settings = Path(SETTINGS_DIR)
    try:
        result = hudmovie.provide(hudmovie.game_dir(settings), settings, __version__,
                                  bool(opt_enhanced_art.value if use_enhanced is None else use_enhanced),
                                  str(opt_enhanced_folder.value or ""), rebuild)
    except Exception as ex:  # BuildFailed, or anything unexpected: never break enabling the mod
        why = str(ex) if isinstance(ex, hudmovie.BuildFailed) else f"{type(ex).__name__}: {ex}"
        set_status(f"Can't build the minimap's HUD movie: {why}. The minimap stays idle.")
        return None
    Redirect.result = result
    how = "read from the movie cache" if result.cached else f"built from your game files in {result.seconds:.2f}s"
    log(f"HUD movie {how} ({len(result.data)} bytes, {result.art} art; inputs "
        f"{', '.join(str(p) for p in result.inputs.values())})")
    for note in result.notes:
        log(note)
    if not result.cached:
        console_line("Built the minimap's HUD movie from your game files; later sessions reuse it.")
    old = hudmovie.game_dir(settings) / hudmovie.INTERFACE / OLD_PACKAGE
    if not Redirect.old_noted and old.exists():
        Redirect.old_noted = True
        log(f"{OLD_PACKAGE} is no longer used (the mod builds its HUD movie itself): you can delete {old}")
    return result.data


def own_movie_info(source: Any) -> Any:
    """A GFxMovieInfo holding the player-built movie, its properties (texture references) copied from `source`,
    the stock movie. Constructed once per build and reused (PLAN_V12 spike: GFx loads such objects)."""
    data = player_movie()
    if data is None:
        return None
    if Redirect.movie_info is not None and Redirect.movie_data is data:
        return Redirect.movie_info
    try:
        info = unrealsdk.construct_object("GFxMovieInfo", getattr(source, "Outer", None), MOVIE_NAME,
                                          int(ObjectFlags.KEEP_ALIVE), source)
        info.RawData = list(data)
    except Exception as ex:
        set_status(f"Couldn't install the minimap's HUD movie ({type(ex).__name__}: {ex}). The minimap stays idle.")
        return None
    release(Redirect.movie_info)
    Redirect.movie_info, Redirect.movie_data = info, data
    return info


def build_status() -> None:
    """The movie's notes (original art, an unrecognised game file, ...) as the status line; nothing when clean."""
    notes = Redirect.result.notes if Redirect.result is not None else []
    if notes:
        set_status(" ".join(notes))
    else:
        clear_status()


def redirect() -> bool:
    """Point the HUD movie template at the player-built movie, or merge into another mod's movie (PLAN_V12)."""
    tmpl = find("WillowHUDGFxMovie", TEMPLATE_PATH)
    if tmpl is None:
        log(f"HUD template {TEMPLATE_PATH} not found; minimap idle")
        return False
    current = tmpl.MovieInfo
    if not is_stock(current) and current != Redirect.movie_info and current != Redirect.merged:
        return merge_into(tmpl, current)
    info = own_movie_info(current)
    if info is None:
        return False
    if Redirect.template is None:
        Redirect.original = tmpl.MovieInfo
    Redirect.template = tmpl
    tmpl.MovieInfo = info
    build_status()
    log(f"HUD template now uses the player-built movie ({len(Redirect.movie_data)} bytes, "
        f"{Redirect.result.art} art; was {Redirect.original})")
    return True


def remake_movie(rebuild: bool = False, use_enhanced: Any = None) -> None:
    """"Use Enhanced artwork" or "Rebuild HUD movie from game files": build again, then re-point the template (or re-merge into
    the other mod's movie). HUDs already up keep their movie; the next level load uses the new one."""
    tmpl = Redirect.template
    if Redirect.merged_active and tmpl is not None and tmpl.MovieInfo == Redirect.merged:
        tmpl.MovieInfo = Redirect.original
    release(Redirect.merged)
    Redirect.merged = Redirect.merged_from = None
    Redirect.merged_active = False
    if player_movie(rebuild=rebuild, use_enhanced=use_enhanced) is not None and Redirect.enabled:
        redirect()


def merge_into(tmpl: Any, foreign: Any) -> bool:
    """Another mod replaced the HUD movie: splice our block into its movie instead of taking the template.

    Never overrides (ADR 0003): a movie that fails the checks stays in place and the minimap stays idle."""
    if foreign == Redirect.refused:
        return False
    ours = player_movie()
    if ours is None:
        return False
    if Redirect.merged is not None and Redirect.merged_from == foreign:
        info = Redirect.merged                               # decision 7: unchanged foreign movie, reuse
    else:
        started = time.time()
        try:
            data = merge_movie(bytes(foreign.RawData), ours, __version__)
            info = unrealsdk.construct_object("GFxMovieInfo", getattr(foreign, "Outer", None), "MinimapMergedHUD",
                                              int(ObjectFlags.KEEP_ALIVE), foreign)
            info.RawData = list(data)
        except MergeRefused as ex:
            Redirect.refused = foreign
            set_status(f"Refused: {ex}. The minimap stays idle.")
            return False
        except Exception as ex:
            Redirect.refused = foreign
            set_status(f"Refused: couldn't build the merged HUD movie ({type(ex).__name__}: {ex}). "
                       "The minimap stays idle.")
            return False
        log(f"merged in {time.time() - started:.2f}s ({len(data)} bytes)")
        release(Redirect.merged)
        Redirect.merged, Redirect.merged_from = info, foreign
    Redirect.template, Redirect.original, Redirect.merged_active = tmpl, foreign, True
    tmpl.MovieInfo = info
    set_status(f"Merged into {foreign}'s HUD movie. A HUD that is already up keeps its movie: "
               "the minimap appears from the next level load.")
    return True


def reconcile() -> None:
    """Called on enable and after every IsMenuLevel: handle another mod taking the HUD template."""
    tmpl = Redirect.template or find("WillowHUDGFxMovie", TEMPLATE_PATH)
    if tmpl is None:
        return
    current = tmpl.MovieInfo
    if current == Redirect.movie_info or (Redirect.merged is not None and current == Redirect.merged):
        return
    if current == Redirect.refused:
        return
    redirect()


def unredirect() -> None:
    tmpl = Redirect.template
    if tmpl is not None and Redirect.original is not None:
        if not Redirect.merged_active or tmpl.MovieInfo == Redirect.merged:
            tmpl.MovieInfo = Redirect.original
        else:
            log("the HUD template changed after the merge: left the template alone")
    # movie_info stays: re-enabling in the same session reuses it while the build is unchanged
    Redirect.template = Redirect.original = Redirect.refused = None
    Redirect.merged_active = False


def uses_minimap_movie(movie: Any) -> bool:
    try:
        return any(info is not None and movie.MovieInfo == info for info in (Redirect.movie_info, Redirect.merged))
    except Exception:
        return False


def start(pc: Any, movie: Any) -> None:
    """Attach the map clip, then collect the zone's objects."""
    S.movie = movie
    if not uses_minimap_movie(movie):
        # This HUD was spawned from the stock movie (before the redirect, or the redirect failed).
        S.phase = "stockhud"
        if Redirect.refused is not None:
            warn_once("stockhud", f"current HUD uses {movie.MovieInfo}; {Redirect.status}")
        else:
            warn_once("stockhud", f"current HUD uses {movie.MovieInfo}, not the minimap's HUD movie: "
                                  "load a save or change area for the minimap to appear")
        return
    if not layout(movie):
        # Either the HUD movie hasn't run its frame-1 script yet (root functions not defined), the
        # attach failed, or the patched GfxHUD.upk isn't installed. Retry; log details as we go.
        S.attempts += 1
        S.phase, S.retry_at = "retry", time.time() + RETRY_INTERVAL
        if S.attempts in (1, 5, 20) or S.attempts == MAX_ATTEMPTS:
            log(f"MinimapCreate failed (attempt {S.attempts}): {describe(movie)}")
        if S.attempts >= MAX_ATTEMPTS:
            log("giving up on this HUD movie: its minimap root functions never ran")
            S.phase = "nopatch"
        return
    log(f"map attached ({get_str(movie, 'mmCreateMode')}) after {S.attempts} retries")
    movie.SetVariableBool("map._visible", False)   # nothing to show until a zone frame is on stage
    cmd(movie, "clear")
    if collect(pc, movie):
        S.phase, S.wait_started = "framewait", time.time()


# ---- collection: one helper call, plain values out ------------------------------------------------

def collect(pc: Any, movie: Any) -> bool:
    """Run classic's own collectors and frame selection on a helper that lives for this call only.

    Init = script FindLandmarks (transitions; sets Anchor and AnchorSize) + native FindObjects
    (interactive objects with CompassIconFrames icons, fast-travel stations, objective slots) +
    FindPlayers. Native frame init needs the zone's LevelLandmarkAnchor; at spawn its level may not have
    streamed in yet (run 6), so no anchor -> retry, backing off. KEEP_ALIVE only guards this call: the GC
    freed a Python-constructed helper while it was still in use (PHASE3 3f). The current icons stay on
    stage until capture swaps them (no blank map during rebuilds, run 9).
    """
    helper = unrealsdk.construct_object("WillowGFxHelperMap", movie, flags=int(ObjectFlags.KEEP_ALIVE))
    old_dlc = S.anchor.get("DLCMap")
    try:
        helper.Init(pc)
        anchor = helper.Anchor
        if anchor is None:
            S.anchor_attempts += 1
            if S.anchor_attempts in (1, 10, 30):
                log(f"no map anchor in the loaded levels yet (attempt {S.anchor_attempts}); waiting")
            delay = ANCHOR_RETRY if S.anchor_attempts < 10 else ANCHOR_RETRY_SLOW
            S.phase, S.retry_at = "anchorwait", time.time() + delay
            return False
        S.anchor = anchor_snapshot(anchor)
        S.zoom_points, S.zoom_has_pawn = fit_inputs(pc), pc.Pawn is not None
        S.sources = object_sources(helper)
        S.givers = find_givers() if opt_givers.value else []
        objectives = [(x, y, z) for _, _, x, y, z, waypoint in S.sources if waypoint]
        S.sources += [(LANDMARK_CLIP, frame, *loc, False) for _, frame, loc in giver_states(pc)
                      if not any(math.dist(loc, o) <= GIVER_OBJECTIVE_UU for o in objectives)]
        # Baseline for change detection = what this collection was built from. Recording it lazily at the
        # next check would miss an objective that moved in between and keep the stale marker.
        try:
            S.objective_key = objective_key(pc)
        except Exception:
            S.objective_key = None
        S.objective_frame, S.tint = objective_style(pc)
        S.mission_key = mission_key(pc)
        # DLC zones share the dlcmap1 frame, whose action loads the DLC movie only when the playhead enters it.
        # A new DLC on the same HUD (T-Bone -> Tartarus, run 14) would keep the old art, so leave the frame first.
        if S.anchor["DLCMap"] not in ("None", old_dlc):
            cmd(movie, "frame", "none")
        helper.InitMapFrame(movie)        # native: map.maps.gotoAndStop(<zone>) or InitDLC(<frame>, <pkg>)
    finally:
        release(helper)
    S.anchor_attempts = 0
    return True


def fit_inputs(pc: Any) -> list[tuple[float, float, float]]:
    """QuickAccessInit's points: the pawn, then every nonzero waypoint slot (gated on RadarMgr)."""
    points = [vec3(pc.Pawn.Location)] if pc.Pawn is not None else []
    gri = pc.WorldInfo.GRI
    if gri is not None and gri.RadarMgr is not None:
        points += [p for slot in gri.ActiveWaypointData if (p := vec3(slot.WaypointLocation)) != (0.0, 0.0, 0.0)]
    return points


def rebuild_in_place(pc: Any, movie: Any) -> None:
    """Enhanced's RebuildMinimapObjects: re-collect and swap the markers within this tick, map visible.

    Same zone frame (the usual case: mission or objective change): capture right away. A different anchor
    whose frame isn't on stage yet waits in framewait with the old markers showing. No anchor (rare
    mid-level): keep the current map.
    """
    old_frame = S.anchor.get("MapFrame")
    if not collect(pc, movie):
        S.phase = "running"
        try:
            S.objective_key = objective_key(pc)    # don't retry every check
        except Exception:
            pass
        warn_once("rebuild-noanchor", "map anchor missing during a rebuild; keeping the current markers")
        return
    if frame_ready(movie) and capture(movie, in_place=True):
        if S.anchor.get("MapFrame") != old_frame:
            log(f"map frame changed to {S.anchor.get('MapFrame')}")
        return
    S.phase, S.wait_started = "framewait", time.time()


def vec3(v: Any) -> tuple[float, float, float]:
    return float(v.X), float(v.Y), float(v.Z)


def anchor_snapshot(anchor: Any) -> dict[str, Any]:
    """The LevelLandmarkAnchor fields the native anchor matrix uses (classic FUN_0146bd60)."""
    rot = anchor.Rotation
    ds3 = anchor.DrawScale3D
    snap = {"name": str(anchor), "level": str(anchor.Outer), "MapFrame": str(anchor.MapFrame),
            "DLCMap": str(anchor.DLCMap), "Location": vec3(anchor.Location),
            "Rotation": (int(rot.Pitch), int(rot.Yaw), int(rot.Roll)), "DrawScale": float(anchor.DrawScale),
            "DrawScale3D": (float(ds3.X), float(ds3.Y)),
            "TextureSize": (float(anchor.TextureSizeX), float(anchor.TextureSizeY))}
    if snap["name"] not in S.recorded:
        snap["fields"] = reflect_fields(anchor)
    return snap


def object_sources(helper: Any) -> list[tuple[str, str, float, float, float, bool]]:
    """World position + icon of every static MapObjectData record (classic UpdateObjects' sources).

    Players and co-op buddies (Player/WPRI) move; the local player is drawn from pc.Pawn every tick.
    Objective records (bWaypoint) carry the slot's location in CustomObjectLoc (FindObjects copies it).
    """
    out = []
    for o in helper.MapObjects:
        if o.Player is not None or o.WPRI is not None:
            continue
        clip, frame = str(o.AS_IconClipPath), str(o.AS_IconClipFrame)
        if not clip or not frame:
            continue
        if o.bWaypoint:
            loc = vec3(o.CustomObjectLoc)
        elif o.ClientInteractiveObject is not None:
            loc = vec3(o.ClientInteractiveObject.Location)
        elif o.Landmark is not None:
            loc = vec3(o.Landmark.Location)
        else:
            loc = vec3(o.CustomObjectLoc)
        if loc == (0.0, 0.0, 0.0):        # the native skips a zero custom vector too
            continue
        out.append((clip, frame, *loc, bool(o.bWaypoint)))
    return out


def reflect_fields(obj: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    try:
        for f in obj.Class._fields():
            if f.Class.Name not in RECORD_KINDS or len(fields) >= 400:
                continue
            try:
                v = obj._get_field(f)
            except Exception as ex:
                v = f"<{type(ex).__name__}>"
            fields[f.Name] = v if isinstance(v, (int, float, bool)) else str(v)[:200]
    except Exception as ex:
        fields["<error>"] = f"{type(ex).__name__}: {ex}"
    return fields


# ---- step B: the native's anchor maths in Python ------------------------------------------------

def anchor_transform(a: dict[str, Any]) -> tuple[float, ...]:
    """World -> anchor-texture space, as classic FUN_0146bd60 + D3DXMatrixInverse build it.

    Rows of the forward matrix are the anchor's rotated axes (FRotationMatrix), X and Y scaled by
    TextureSize * DrawScale3D * DrawScale, then Location. Row-vector convention: q = [x y z 1] * M^-1.
    """
    pitch, yaw, roll = (r * math.tau / 65536.0 for r in a["Rotation"])
    sp, cp, sy, cy, sr, cr = (math.sin(pitch), math.cos(pitch), math.sin(yaw), math.cos(yaw),
                              math.sin(roll), math.cos(roll))
    sx = a["TextureSize"][0] * a["DrawScale3D"][0] * a["DrawScale"]
    sz = a["TextureSize"][1] * a["DrawScale3D"][1] * a["DrawScale"]
    lx, ly, lz = a["Location"]
    fwd = [[cp * cy * sx, cp * sy * sx, sp * sx, 0.0],
           [(sr * sp * cy - cr * sy) * sz, (sr * sp * sy + cr * cy) * sz, -sr * cp * sz, 0.0],
           [-(cr * sp * cy + sr * sy), cy * sr - cr * sp * sy, cr * cp, 0.0],
           [lx, ly, lz, 1.0]]
    return tuple(x for row in invert4(fwd) for x in row)


def invert4(m: list[list[float]]) -> list[list[float]]:
    """Gauss-Jordan with partial pivoting; ValueError if singular (zero-size anchor)."""
    a = [row[:] + [1.0 if i == j else 0.0 for j in range(4)] for i, row in enumerate(m)]
    for c in range(4):
        p = max(range(c, 4), key=lambda i: abs(a[i][c]))
        if abs(a[p][c]) < 1e-12:
            raise ValueError("singular anchor matrix")
        a[c], a[p] = a[p], a[c]
        pv = a[c][c]
        a[c] = [x / pv for x in a[c]]
        for i in range(4):
            if i != c and a[i][c] != 0.0:
                f = a[i][c]
                a[i] = [x - f * y for x, y in zip(a[i], a[c])]
    return [row[4:] for row in a]


def coord_scale(anchor_size: tuple[float, float], clip_w: float, clip_h: float) -> tuple[float, float]:
    """Aspect correction from classic InitMapFrameVars: art (ClipSize) vs anchor texture (AnchorSize)."""
    fx, fy = anchor_size[0] / clip_w, anchor_size[1] / clip_h
    if fy < fx:
        return anchor_size[0] / (clip_w * fy), 1.0
    return 1.0, anchor_size[1] / (clip_h * fx)


def frame_ready(movie: Any) -> bool:
    """A real zone frame is on stage: frame 1 is "none" (a blank shape whose width is also finite)."""
    frame = get_num(movie, "map.maps._currentframe")
    width = get_num(movie, "map.maps.themap._width")
    return isinstance(frame, float) and math.isfinite(frame) and frame > 1 and finite_positive(width)


def capture(movie: Any, in_place: bool = False) -> bool:
    """The zone art is on stage: compute the transform, project every landmark and draw from Python.

    in_place (rebuild while running): visibility is left alone and the caller redraws the player icon and
    threat dots in the same tick, so the swap never renders a blank map (Flash draws after the script)."""
    w = get_num(movie, "map.maps.themap._width")
    h = get_num(movie, "map.maps.themap._height")
    if not (finite_positive(w) and finite_positive(h)):
        return False
    try:
        S.xf = anchor_transform(S.anchor)
    except (ValueError, KeyError) as ex:
        warn_once("xf:" + S.anchor.get("name", "?"), f"unusable map anchor {S.anchor.get('name')}: {ex}")
        return False
    S.cs = coord_scale(S.anchor["TextureSize"], w, h)    # ratio only: same at any zoom
    fit_anchor = {k: v for k, v in S.anchor.items() if k != "fields"}
    # Enhanced fits once per HUD (PLAN_V14); "Objective" zoom mode also refits for a new tracked mission or status
    new_mission = opt_zoom_mode.value == "Objective" and S.fit_mission != S.mission_key
    if S.fit_anchor != fit_anchor or new_mission:
        scale = get_num(movie, "map.maps.themap._xscale")
        if not finite_positive(scale):
            return False
        S.fit_points, S.fit_has_pawn = S.zoom_points[:], S.zoom_has_pawn
        S.fit_art = (w * 100 / scale, h * 100 / scale)
        S.fit_raw, S.fit = fit_zoom(S.fit_points, S.xf, S.cs, *S.fit_art)
        S.fit_anchor, S.fit_mission = fit_anchor, S.mission_key
        S.fit_pending = True              # confirm once the map is shown (refit_when_shown)
    S.frame = get_num(movie, "map.maps._currentframe")
    S.marks = []
    for clip, frame, x, y, z, waypoint in S.sources:
        u, v = to_map(x, y, z)
        if math.isfinite(u) and math.isfinite(v):
            if waypoint:
                S.marks.append((clip, S.objective_frame, u, v, 0.0, S.tint))
            else:
                S.marks.append((clip, frame, u, v, 0.0, None))
    record_anchor(w, h)
    S.phase = "running"
    place_static(movie)
    S.next_threats = 0.0                  # dots were cleared with the icons: redraw on this tick
    if not in_place:
        S.shown = None                    # the next tick decides visibility (hidden_reason)
    movie.SetVariableBool("p1.bearing._visible", not opt_hide_compass.value)
    log(f"map ready: {S.anchor['MapFrame']} (frame {S.frame:g}), {len(S.marks)} markers")
    return True


def fit_zoom(points: list[tuple[float, float, float]], xf: tuple[float, ...],
             cs: tuple[float, float], art_w: float, art_h: float) -> tuple[Any, float]:
    """QuickAccessInit's world-box corner fit, then AnalogScale(+8) (PLAN_V10 research 1).

    Keep the signed corner projection, including pitch/roll, just as the native does.
    Zero projected spans impose no limit on that axis.
    """
    if len(points) < 2:
        return None, ENH_ZOOM
    spans = [max(p[i] for p in points) - min(p[i] for p in points) for i in range(3)]
    du = sum(spans[i] * xf[i * 4 + 1] for i in range(3)) * cs[0] * art_w / 100
    dv = -sum(spans[i] * xf[i * 4] for i in range(3)) * cs[1] * art_h / 100
    raw = 0.5 * min(MASK_W / du if du else math.inf, -MASK_H / dv if dv else math.inf)
    return raw, min(400.0, max(100.0, raw) + 8.0)


def refit_when_shown(pc: Any, movie: Any) -> None:
    """Redo the capture's fit once, the first time the map is shown afterwards.

    After a level change the capture can run while the pawn still has its previous zone's location (run 15:
    Tartarus coordinates in Arid gave 108% instead of 400%). Enhanced fits at HUD init, after loading; by the
    time the map shows (no loading movie, live levels settled) the pawn has been placed. Only the pawn point
    is refreshed: the capture's waypoints stay, since objective changes keep the fit (as in Enhanced). Same
    points: no change. Different points: refit and redraw."""
    S.fit_pending = False
    waypoints = S.fit_points[1:] if S.fit_has_pawn else S.fit_points
    points = ([vec3(pc.Pawn.Location)] if pc.Pawn is not None else []) + waypoints
    if points == S.fit_points:
        return
    S.fit_points, S.fit_has_pawn = points, pc.Pawn is not None
    S.fit_raw, fit = fit_zoom(points, S.xf, S.cs, *S.fit_art)
    if fit != S.fit:
        S.fit = fit
        place_static(movie)


def zoom_percent() -> float:
    """Apply the user's multiplier to Enhanced's captured objective fit."""
    return S.fit * float(opt_zoom.value.rstrip("%")) / 100.0


def icon_percent() -> float:
    """Icon scale: our clip has Enhanced's layout, so its icons are already at Enhanced's size at 100%."""
    return float(opt_icon_size.value)


def place_static(movie: Any) -> None:
    """(Re)draw the snapshot: clear dynamic clips, apply zoom and icon size, add every landmark. The player
    icon is recreated by the next tick."""
    cmd(movie, "clear")
    cmd(movie, "iconscale", icon_percent())
    cmd(movie, "scale", zoom_percent())
    for clip, frame, u, v, angle, rgb in S.marks:
        if rgb is None:
            cmd(movie, "add", clip, u, v, angle, frame)
        else:
            cmd(movie, "add", clip, u, v, angle, frame, rgb)


def record_anchor(clip_w: float, clip_h: float) -> None:
    """Log each anchor once per session with the computed transform (new zones, DLC checks)."""
    a = S.anchor
    if "fields" not in a or a["name"] in S.recorded:
        return
    S.recorded.add(a["name"])
    try:
        rec = {"t": time.time(), "version": __version__, "anchor": a["name"], "level": a["level"],
               "frame": S.frame, "Transform": S.xf, "CoordScale": S.cs, "AnchorSize": a["TextureSize"],
               "ClipSize": (clip_w, clip_h), "markers": len(S.marks), "fields": a["fields"]}
        with ANCHOR_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except Exception as ex:
        warn_once("anchorlog", f"couldn't record anchor fields ({type(ex).__name__}: {ex})")


def to_map(x: float, y: float, z: float) -> tuple[float, float]:
    """World -> 0..1 across the zone art (classic FUN_01414000)."""
    m = S.xf
    u = x * m[0] + y * m[4] + z * m[8] + m[12]
    v = x * m[1] + y * m[5] + z * m[9] + m[13]
    return (v + 0.5) * S.cs[0], (0.5 - u) * S.cs[1]


# ---- threats ---------------------------------------------------------------------------------------

def radar_threats(pc: Any) -> Any:
    """Active RemoteDynamicIcons locations, or None if there is no radar manager.

    Enhanced's UpdateThreats (FUN_141487bd0) copies exactly these: every bActive entry of
    GRI.RadarMgr.RemoteDynamicIcons[MAX_ACTIVE_DYNAMIC_ICONS = 18], no range or type filter.
    """
    gri = getattr(pc.WorldInfo, "GRI", None)
    mgr = getattr(gri, "RadarMgr", None) if gri is not None else None
    if mgr is None:
        return None
    return [vec3(icon.Location) for icon in mgr.RemoteDynamicIcons if icon.bActive]


def shown_in_radar(pawn: Any) -> bool:
    try:
        engine = pawn.Controller.MyRuleEngine
        return bool(engine.IsPawnShownInRadarForCurrentState()) if engine is not None else True
    except Exception:
        return True


def pawn_threats(pc: Any, range_uu: float) -> list[tuple[float, float, float]]:
    """Fallback: hostile, alive pawns within range that the rule engine would show on the radar."""
    me = pc.Pawn
    if me is None:
        return []
    r2 = range_uu * range_uu
    ml = me.Location
    out = []
    p = pc.WorldInfo.PawnList
    guard = 0
    while p is not None and guard < 2048:
        guard += 1
        try:
            if p != me and p.IsAliveAndWell() and me.IsEnemy(p):
                l = p.Location
                if (l.X - ml.X) ** 2 + (l.Y - ml.Y) ** 2 <= r2 and shown_in_radar(p):
                    out.append(vec3(l))
        except Exception:
            pass
        p = p.NextPawn
    return out


def check_radar_empty(pc: Any) -> None:
    """The radar list is replicated state the game fills; if it stays empty while enemies are close,
    this game/build doesn't populate it here: fall back to the pawn scan for the session."""
    S.radar_empty += 1
    if S.radar_empty % RADAR_PROBE_EVERY:
        return
    if pawn_threats(pc, RADAR_PROBE_RANGE_UU):
        S.radar_misses += 1
        if S.radar_misses >= RADAR_MISS_LIMIT:
            S.threat_source = "pawns"
            log("compass radar list stays empty with enemies nearby; using the pawn scan for enemy dots")


def threat_points(pc: Any) -> list[tuple[float, float, float]]:
    range_uu = opt_threat_range.value * UU_PER_M
    if S.threat_source == "radar":
        try:
            pts = radar_threats(pc)
        except Exception as ex:
            warn_once("radar:" + type(ex).__name__, f"radar list unavailable ({type(ex).__name__}: {ex})")
            pts = None
        if pts is None:
            S.threat_source = "pawns"
            log("no compass radar manager; using the pawn scan for enemy dots")
        elif pts:
            S.radar_empty = S.radar_misses = 0
        else:
            check_radar_empty(pc)
    if S.threat_source != "radar":
        pts = pawn_threats(pc, range_uu or PAWN_FALLBACK_RANGE_M * UU_PER_M)
    if range_uu and pc.Pawn is not None:
        ml = pc.Pawn.Location
        r2 = range_uu * range_uu
        pts = [p for p in pts if (p[0] - ml.X) ** 2 + (p[1] - ml.Y) ** 2 <= r2]
    return pts


def threat_string(pc: Any) -> str:
    parts = []
    for x, y, z in threat_points(pc):
        tx, ty = to_map(x, y, z)
        if math.isfinite(tx) and math.isfinite(ty):
            parts.append(f"{tx:.5f},{ty:.5f}")
    return "|".join(parts)


# ---- missions --------------------------------------------------------------------------------------

def mission_tracker() -> Any:
    """The game's MissionTracker (as Objective Distance finds it), cached through a weak reference."""
    t = S.tracker()
    if t is None:
        try:
            found = list(unrealsdk.find_all("MissionTracker"))
        except Exception:
            found = []
        t = found[-1] if found else None
        S.tracker = WeakPointer(t)
    return t


def tracked_mission() -> Any:
    tracker = mission_tracker()
    return tracker.ActiveMission if tracker is not None else None


def mission_status(pc: Any, mission: Any) -> Any:
    """EMissionStatus of a mission in the current playthrough (WillowPlayerController mission data)."""
    if mission is None:
        return None
    playthrough = pc.GetCurrentPlaythrough()
    for info in pc.MissionPlaythroughData:
        if info.PlayThroughNumber != playthrough:
            continue
        for entry in info.MissionList:
            if entry.MissionDef == mission:
                return int(entry.Status)
    return None


def mission_key(pc: Any) -> tuple[str, str]:
    """The tracked mission and its status: what the "Objective" zoom mode refits on (PLAN_V14 decision 2)."""
    mission = tracked_mission()
    try:
        status = mission_status(pc, mission)
    except Exception:
        status = None
    return str(mission), str(status)


def objective_style(pc: Any) -> tuple[str, Any]:
    """(frame, tint) for the objective slots. Like Enhanced (FUN_14138d240, PHASE3 3ak): the tracked mission's
    status picks the frame, "turnin" when ready to hand in, "newmission" when not started, else the plain
    "objective" diamond; Enhanced never tints them. "Tint objective diamonds" keeps the diamond and tints it gold
    or green instead, the style of v0.6 to v0.13.0 (None = stock colour)."""
    try:
        status = mission_status(pc, tracked_mission())
    except Exception as ex:
        warn_once("status:" + type(ex).__name__, f"mission status unavailable ({type(ex).__name__}: {ex})")
        return "objective", None
    if opt_objective_tint.value:
        return "objective", STATUS_TINT.get(status)
    return STATUS_FRAME.get(status, "objective"), None


def objective_key(pc: Any) -> tuple[str, ...]:
    """What the map's objective markers depend on: tracked mission and its status, its waypoints, the
    visible levels.

    Classic FindObjects only appends and UpdateObjects rereads the eight waypoint slots by ordinal, so
    records drift between slots (ENHANCED_NATIVE.md 4). Enhanced instead copies the locations and rebuilds
    on mission changes; so does this. Strings of freshly read objects only: nothing native is held.
    """
    mission = tracked_mission()
    target = getattr(mission, "TargetWaypointDefinition", None) if mission is not None else None
    turn_in = getattr(mission, "TurnInWaypointDefinition", None) if mission is not None else None
    try:
        status = mission_status(pc, mission)
    except Exception:
        status = None
    givers = tuple(f"{name}:{frame}" for name, frame, _ in giver_states(pc))   # accept/hand in -> rebuild
    return (str(mission), str(status), str(target), str(turn_in), *waypoint_key(pc), *live_levels(pc), *givers)


# ---- mission givers (PLAN_V08 3) ---------------------------------------------------------------------

def willow_globals() -> Any:
    """The live WillowGlobals (not its class default), cached through a weak reference."""
    g = S.globals_ref()
    if g is None:
        try:
            found = [o for o in unrealsdk.find_all("WillowGlobals", exact=False) if "Default__" not in str(o)]
        except Exception:
            found = []
        g = found[-1] if found else None
        S.globals_ref = WeakPointer(g)
    return g


def find_givers() -> list[Any]:
    """Interactive objects with mission directives (only WillowInteractiveObject implements
    IMissionDirector, NPC givers included), from the same list native FindObjects walks."""
    try:
        g = willow_globals()
        ios = g.ClientInteractiveObjects if g is not None else []
        return [WeakPointer(io) for io in ios if io is not None and len(io.MissionDirectives) > 0]
    except Exception as ex:
        warn_once("givers:" + type(ex).__name__, f"mission givers unavailable ({type(ex).__name__}: {ex})")
        return []


def script_count(fn: Any, pc: Any) -> int:
    """Return value of an IMissionDirector Get*Missions(WPC, out Array) call. pyunrealsdk requires the out
    parameter as a positional argument (run 12: "missing 1 required positional argument") and returns
    (ReturnValue, out params...)."""
    r = fn(pc, [])
    if isinstance(r, tuple):
        r = r[0]
    return int(r or 0)


def giver_states(pc: Any) -> list[tuple[str, str, tuple[float, float, float]]]:
    """(name, frame, location) per giver with something for this player: turnin where a finished mission can
    be handed in (GetRedeemableMissions), else newmission where one can start (GetEligibleMissions).
    These are classic's own availability rules (GetMissionEligibility: level, dependencies, not taken)."""
    if not opt_givers.value:
        return []
    out = []
    for ref in S.givers:
        io = ref()
        if io is None:
            continue
        try:
            if script_count(io.GetRedeemableMissions, pc) > 0:
                frame = "turnin"
            elif script_count(io.GetEligibleMissions, pc) > 0:
                frame = "newmission"
            else:
                continue
            out.append((str(io), frame, vec3(io.Location)))
        except Exception as ex:
            warn_once("giver:" + type(ex).__name__, f"mission giver check failed ({type(ex).__name__}: {ex})")
    return out


def waypoint_key(pc: Any) -> tuple[str, ...]:
    """Live objective positions: WillowGameReplicationInfo.ActiveWaypointData[i].WaypointLocation,
    rounded to WAYPOINT_GRID units so small drift doesn't rebuild every check (run 8 stale diamond)."""
    out = []
    gri = getattr(pc.WorldInfo, "GRI", None)
    if gri is None:
        return ()
    for i, slot in enumerate(gri.ActiveWaypointData):
        loc = slot.WaypointLocation
        if loc.X or loc.Y or loc.Z:
            out.append(f"wp{i}:{round(loc.X / WAYPOINT_GRID)},{round(loc.Y / WAYPOINT_GRID)}")
    return tuple(out)


def live_levels(pc: Any) -> tuple[str, ...]:
    """The persistent level plus visible streaming levels, as strings (the diagnostics collector's epoch,
    steam-deck-scripts BL1MapDiagnostics/collector.py context())."""
    info = pc.WorldInfo
    levels = [str(info.PersistentLevel)] if getattr(info, "PersistentLevel", None) is not None else []
    for streaming in info.StreamingLevels:
        if streaming is not None and streaming.bIsVisible and streaming.LoadedLevel is not None:
            levels.append(str(streaming.LoadedLevel))
    return tuple(sorted(levels))


# ---- visibility ------------------------------------------------------------------------------------

def hidden_reason(pc: Any, movie: Any, now: float) -> str:
    """Why the minimap must not draw right now ("" = show it).

    Enhanced's native pipeline has no visibility gate (ENHANCED_NATIVE.md 1): its map is p1.map and the
    HUD hides it. Ours is _root.map, so the mod mirrors the game's own gates:
    - loading movie: the travel "blue tunnel" (WillowPlayerController.IsLoadingMoviePlaying());
    - HUD off / cinematic / status menu / dead: what WillowPlayerController.ShowStatusMenu checks
      (myHUD.bShowHUD, bCinematicMode) plus the open menu and a dead pawn;
    - p1 hidden: the stock HUD clip is hidden;
    - settling: the live-level set changed less than SETTLE_SECONDS ago (the diagnostics collector waits
      for three seconds of stable ready context).
    """
    hud = pc.myHUD
    pawn = pc.Pawn
    checks = (
        ("loading movie", lambda: pc.IsLoadingMoviePlaying()),
        ("HUD off", lambda: hud is None or not hud.bShowHUD),
        ("cinematic", lambda: pc.bCinematicMode),
        ("status menu", lambda: pc.bStatusMenuOpen),
        # classic pawns have no Health property (run 8): use the native Pawn.IsAliveAndWell()
        ("no live pawn", lambda: pawn is None or not pawn.IsAliveAndWell()),
        ("HUD clip hidden", lambda: not movie.GetVariableBool("p1._visible")),
    )
    for reason, test in checks:
        try:
            if test():
                return reason
        except Exception as ex:   # one broken check is skipped; it must not disable the others (run 8)
            warn_once("vis:" + reason, f"visibility check '{reason}' unavailable ({type(ex).__name__}: {ex})")
    if S.epoch_since is None or now - S.epoch_since < SETTLE_SECONDS:
        return "settling"
    return ""


def update_epoch(pc: Any, now: float) -> None:
    """Restart the settle clock whenever the live-level set changes (survives map rebuilds)."""
    try:
        epoch = live_levels(pc)
    except Exception as ex:
        warn_once("epoch:" + type(ex).__name__, f"level check unavailable ({type(ex).__name__}: {ex})")
        return
    if epoch != S.epoch:
        S.epoch, S.epoch_since = epoch, now


def set_visible(movie: Any, show: bool, reason: str) -> None:
    """Show/hide the map; while docked and shown, the ECHO/mission column sits where Enhanced puts it
    (p<N>.UpdateEchoPosition), and returns to its authored place whenever the map hides."""
    if show != S.shown:
        movie.SetVariableBool("map._visible", show)
        S.shown = show
        if reason != S.last_hidden_reason:
            log(f"minimap {'shown' if show else 'hidden: ' + reason}")
            S.last_hidden_reason = reason
    want = show and S.dock is not None
    if want != S.hud_on:
        hud_shift(movie, want)


# ---- per tick --------------------------------------------------------------------------------------

def tick(pc: Any) -> None:
    now = time.time()
    if now < S.next_tick:
        return
    S.next_tick = now + TICK_INTERVAL

    movie = current_hud_movie(pc)
    if movie is None:
        if S.phase != "idle":                # S.movie may already read None (destroyed)
            S.reset()
        return
    if pc.Pawn is None:                  # main menu, loading, dead/respawning: nothing to show
        return
    if now >= S.save_next:
        S.save_next = now + SAVE_CHECK_INTERVAL
        watch_save(pc)
    if now >= S.next_epoch_check:
        S.next_epoch_check = now + EPOCH_CHECK_INTERVAL
        update_epoch(pc, now)
    if movie != S.movie:                 # new HUD (level load, fast travel): start over
        S.reset()
        start(pc, movie)
        return
    if S.phase in ("nopatch", "stockhud"):
        return
    if S.phase == "retry":
        if now >= S.retry_at:
            start(pc, movie)
        return
    if S.phase == "anchorwait":
        if now >= S.retry_at and collect(pc, movie):
            S.phase, S.wait_started = "framewait", now
        return
    if S.phase == "framewait":
        if frame_ready(movie) and capture(movie):
            pass
        elif now - S.wait_started > READY_TIMEOUT:
            log(f"zone frame not ready after {READY_TIMEOUT:g}s (frame {get_num(movie, 'map.maps._currentframe')}); "
                "retrying")
            S.phase, S.retry_at = "anchorwait", now + ANCHOR_RETRY
        return

    if S.layout_dirty:
        S.layout_dirty = False
        apply_layout_now(movie)
    elif now >= S.next_dock_check:
        S.next_dock_check = now + DOCK_CHECK_INTERVAL
        check_dock(movie)
    if S.vog_until > now and now >= S.vog_next:
        watch_vog(pc, now)
    if S.sp_until > now and now >= S.sp_next:
        watch_particles(pc, now)
    if S.vog_fast_until > now or now >= S.vog_clip_next:
        S.vog_clip_next = now + DOCK_CHECK_INTERVAL
        watch_vog_clip(movie)
    if S.rebuild_pending:
        if S.rebuild_refit:
            S.fit_anchor = None
        S.rebuild_pending = S.rebuild_refit = False
        rebuild_in_place(pc, movie)
    elif now >= S.next_objective_check:
        S.next_objective_check = now + OBJECTIVE_CHECK_INTERVAL
        try:
            key = objective_key(pc)
        except Exception as ex:      # optional: never let it reset the map every tick
            warn_once("objkey:" + type(ex).__name__, f"objective check unavailable ({type(ex).__name__}: {ex})")
            key = S.objective_key
        if S.objective_key is None:
            S.objective_key = key
        elif key != S.objective_key:
            log("tracked mission or visible area changed; rebuilding map objects in place")
            rebuild_in_place(pc, movie)
    if S.phase != "running":         # a rebuild moved to a new zone frame that isn't on stage yet
        return
    # Positions keep updating while hidden, so the map is already right when it reappears.
    pawn = pc.Pawn
    px, py = to_map(*vec3(pawn.Location))
    if math.isfinite(px) and math.isfinite(py):
        deg = pawn.Rotation.Yaw * 360.0 / 65536.0       # native Angle conversion (PHASE0, classic-decision)
        cmd(movie, "tick", px, py, deg, opt_rotate.value, float(opt_rotation_offset.value))

    if now >= S.next_threats:
        S.next_threats = now + THREAT_INTERVAL
        cmd(movie, "threats", threat_string(pc) if opt_threats.value else "")

    try:
        reason = hidden_reason(pc, movie, now)
    except Exception as ex:      # a failing check must not reset the map every tick; show it instead
        warn_once("vis:" + type(ex).__name__, f"visibility check unavailable ({type(ex).__name__}: {ex})")
        reason = ""
    set_visible(movie, not reason, reason)
    if S.fit_pending and not reason:
        refit_when_shown(pc, movie)
        S.next_threats = 0.0              # a redraw clears the dots: redraw them on the next tick


@hook("WillowGame.WillowPlayerController:PlayerTick", Type.PRE)
def on_player_tick(obj: Any, args: Any, ret: Any, func: Any) -> None:
    if obj != get_pc():
        return
    try:
        tick(obj)
    except Exception as ex:  # never let a minimap error break the game loop
        warn_once("tick:" + type(ex).__name__, f"tick error ({type(ex).__name__}: {ex}); resetting")
        S.reset()


def rebuild(refit: bool = True) -> None:
    """Re-collect landmarks/objectives on the next tick: in place while the map runs (no blank map);
    otherwise start over. refit=False keeps the zoom (closing the status menu, like Enhanced's
    RebuildMinimapObjects; PLAN_V14)."""
    if S.phase == "running":
        S.rebuild_pending = True
        S.rebuild_refit = S.rebuild_refit or refit
        return
    movie = S.movie
    teardown_hud = S.hud_on
    S.reset()
    if movie is not None:
        try:
            if teardown_hud:
                hud_cmd(movie, 0, LAYOUTS["16:9"])
            cmd(movie, "clear")
        except Exception:
            pass


@keybind("Rebuild minimap", "F8", description="Re-collect landmarks and objectives.")
def on_rebuild_key() -> None:
    rebuild()


@keybind("Minimap diagnostics", "F7", description="Write the minimap's current state to the SDK log.")
def on_diag_key() -> None:
    pc = get_pc()
    movie = current_hud_movie(pc) if pc is not None else None
    info: dict[str, Any] = {"version": __version__, "phase": S.phase, "attempts": S.attempts,
                            "pawn": str(pc.Pawn) if pc else None, "same_movie": movie == S.movie,
                            "template.MovieInfo": str(Redirect.template.MovieInfo) if Redirect.template else None,
                            "hud_merge": Redirect.status or None,
                            "hud.MovieInfo": str(movie.MovieInfo) if movie is not None else None}
    mesh = vog_mesh(pc) if pc is not None else None
    info["angel"] = vog_state(mesh) if mesh is not None else None
    info["vog"] = vog_clip_state(movie) if movie is not None else None
    info["save_indicator"] = save_state(pc) if pc is not None else None
    try:
        info["screen_particles"] = [particle_record(r) for r in particle_records(pc)] if pc is not None else None
    except Exception as ex:
        info["screen_particles"] = f"<{type(ex).__name__}: {ex}>"
    r = Redirect.result
    info["hud_movie"] = None if r is None else {
        "art": r.art, "cached": r.cached, "seconds": round(r.seconds, 2), "bytes": len(r.data),
        "inputs": {name: str(path) for name, path in r.inputs.items()},
        "enhanced_folder": str(r.enhanced) if r.enhanced else None, "recognised": r.recognised, "notes": r.notes}
    if movie is not None:
        info.update(describe(movie))
    info.update(anchor=S.anchor.get("name"), map_frame=S.anchor.get("MapFrame"), anchor_attempts=S.anchor_attempts,
                markers=len(S.marks), tint=S.tint, givers=len(S.givers),
                giver_icons=[f for _, f, _ in giver_states(pc)] if pc is not None else None,
                zoom=zoom_percent(), icon_scale=icon_percent(),
                zoom_fit={"points": S.fit_points, "raw": S.fit_raw, "fitted": S.fit, "final": zoom_percent()},
                captured_frame=S.frame, CoordScale=S.cs, Transform=S.xf,
                threat_source=S.threat_source, radar_empty=S.radar_empty, radar_misses=S.radar_misses,
                position=opt_position.value, dock=S.dock, dock_mode=S.dock_mode, hud_shifted=S.hud_on,
                p1=S.p1_sig)
    if movie is not None:
        info.update(dock_b=get_num(movie, "mmDockB"), echo_x=get_num(movie, "p1.echo._x"),
                    echo_x0=get_num(movie, "mmEchoX0"), hud_fixes=get_num(movie, "mmHudFixes"))
    if pc is not None:
        try:
            pts = radar_threats(pc)
            info["radar_active"] = None if pts is None else len(pts)
        except Exception as ex:
            info["radar_active"] = f"<{type(ex).__name__}: {ex}>"
    if movie is not None:
        info.update(frame=get_num(movie, "map.maps._currentframe"),
                    themap_w=get_num(movie, "map.maps.themap._width"))
    log(f"diagnostics: {info}")
    if pc is not None:
        try:
            pc.Player.ViewportClient.ViewportConsole.OutputText(
                "[Classic Minimap] Diagnostic snapshot written to Binaries/Plugins/unrealsdk.log.")
        except Exception as ex:
            warn_once("diag-console", f"diagnostic console feedback unavailable ({type(ex).__name__}: {ex})")


@hook("WillowGame.StatusMenuExGFxMovie:OnClose", Type.POST)
def on_status_menu_close(obj: Any, args: Any, ret: Any, func: Any) -> None:
    rebuild(refit=False)  # missions/waypoints may have changed while the menu was open; the zoom mode decides refits


# ---- Angel's screen (run 23 spike, PHASE3 3an) ---------------------------------------------------------
# PlayVoGEchoCall renders Angel's video onto GFxUIManager.ScreenMesh, a 3D mesh attached to the camera, so the HUD
# always draws over it; classic places it top right, behind the minimap. Enhanced positions it from
# GlobalsDefinition.VoG*Position (which classic lacks). This logs the mesh and optionally tries Enhanced's value.

def vog_mesh(pc: Any) -> Any:
    manager = getattr(pc, "GFxUIManager", None)
    return getattr(manager, "ScreenMesh", None) if manager is not None else None


def vog_translation(mesh: Any) -> tuple[float, float, float]:
    t = mesh.Translation
    return round(float(t.X), 3), round(float(t.Y), 3), round(float(t.Z), 3)


def vog_state(mesh: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"mesh": str(mesh)}
    for name, fields in (("Translation", "XYZ"), ("Rotation", ("Pitch", "Yaw", "Roll")), ("Scale", None),
                         ("Scale3D", "XYZ"), ("AbsoluteTranslation", None), ("Owner", None)):
        try:
            v = getattr(mesh, name)
            out[name] = tuple(float(getattr(v, f)) for f in fields) if fields else str(v)
        except Exception as ex:
            out[name] = f"<{type(ex).__name__}>"
    return out


@hook("WillowGame.WillowPlayerController:PlayVoGEchoCall", Type.POST)
def on_vog_call(obj: Any, args: Any, ret: Any, func: Any) -> None:
    try:
        mesh = vog_mesh(obj)
        if mesh is None:
            warn_once("vog:nomesh", "Angel call: no GFxUIManager.ScreenMesh to inspect")
            return
        log(f"Angel call: screen mesh {vog_state(mesh)}")
        S.vog_last, S.vog_until, S.vog_next = vog_translation(mesh), time.time() + VOG_WATCH_SECONDS, time.time() + 1.0
    except Exception as ex:  # an experiment must never break the call
        warn_once("vog:" + type(ex).__name__, f"Angel call inspection failed ({type(ex).__name__}: {ex})")


def watch_vog(pc: Any, now: float) -> None:
    """During the watch window: log native moves of the screen mesh (never seen in classic; runs 24-30)."""
    S.vog_next = now + 1.0
    try:
        mesh = vog_mesh(pc)
        t = vog_translation(mesh)
    except Exception:
        S.vog_until = 0.0
        return
    if t != S.vog_last:
        log(f"Angel call: the screen mesh moved to {t} (was {S.vog_last})")
        S.vog_last = t


# Run 24 (PHASE3 3an): PlayVoGEchoCall never ran and there was no screen mesh. The HUD movie's root clip `vog`
# (every edition authors it top centre, (412, 90), 456 x 256.6) shows external image "texture1", the name ECHO videos
# are bound to, so Angel probably plays there. Log that clip: on F7, on every change (once a second), and every tick
# for a while after a script-level ECHO call, to see whether classic moves it top right.

def vog_clip_state(movie: Any) -> Any:
    """The root vog clip's placement, or None when the movie has no such clip."""
    nums = {k: get_num(movie, "vog." + k) for k in VOG_NUMBERS}
    if not finite(nums["_x"]):
        return None
    out: dict[str, Any] = {k: round(v, 1) if finite(v) else v for k, v in nums.items()}
    try:
        out["_visible"] = bool(movie.GetVariableBool("vog._visible"))
    except Exception as ex:
        out["_visible"] = f"<{type(ex).__name__}>"
    return out


def watch_vog_clip(movie: Any) -> None:
    try:
        state = vog_clip_state(movie)
    except Exception as ex:  # a diagnostic must never break the tick
        warn_once("vogclip:" + type(ex).__name__, f"vog clip check failed ({type(ex).__name__}: {ex})")
        return
    if state != S.vog_clip:
        S.vog_clip = state
        log(f"Angel's screen (root vog): {state}")


def on_echo_call(name: str) -> None:
    log(f"ECHO call ({name}); watching the root vog clip for {VOG_FAST_SECONDS:g}s")
    S.vog_fast_until = time.time() + VOG_FAST_SECONDS


@hook("WillowGame.WillowPlayerController:Behavior_PlayEchoCall", Type.PRE)
def on_behavior_echo_call(obj: Any, args: Any, ret: Any, func: Any) -> None:
    on_echo_call("Behavior_PlayEchoCall")


@hook("WillowGame.WillowPlayerController:ClientPlayEchoCall", Type.PRE)
def on_client_echo_call(obj: Any, args: Any, ret: Any, func: Any) -> None:
    on_echo_call("ClientPlayEchoCall")


@hook("WillowGame.WillowHUDGFxMovie:PlayEchoCall", Type.PRE)
def on_hud_echo_call(obj: Any, args: Any, ret: Any, func: Any) -> None:
    on_echo_call("PlayEchoCall")


# Run 26 (PHASE3 3aq): with the root vog clip 0 x 0 and no screen mesh, Angel's video still sat behind the map.
# Classic shows it as a screen particle: ShowScreenParticle attaches a ParticleSystemComponent to the pawn and
# SetUpVoGScreenParticle puts the ECHO video into its material. Log the records (template, component placement,
# each emitter's modules) and, for a while, the component against the camera, to find what places it.

def type_name(o: Any) -> str:
    cls = getattr(o, "Class", None)
    return str(getattr(cls, "Name", None) or getattr(o, "_type", None) or type(o).__name__)


def vec_tuple(v: Any) -> tuple[float, float, float]:
    return round(float(v.X), 1), round(float(v.Y), 1), round(float(v.Z), 1)


def safe_fields(o: Any, names: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in names:
        try:
            v = getattr(o, name)
            if hasattr(v, "X"):
                v = vec_tuple(v)
            elif hasattr(v, "Pitch"):
                v = (int(v.Pitch), int(v.Yaw), int(v.Roll))
            elif not isinstance(v, (bool, int, float)):
                v = str(v)
            out[name] = v
        except Exception as ex:
            out[name] = f"<{type(ex).__name__}>"
    return out


def distribution_state(raw: Any) -> Any:
    table = getattr(raw, "LookupTable", None)
    if table is not None:                       # cooked: only the baked lookup table is left (run 27)
        dist = getattr(raw, "Distribution", None)
        return {"dist": type_name(dist) if dist is not None else None, "op": str(getattr(raw, "Op", "")),
                "chunk": getattr(raw, "LookupTableChunkSize", None), "table": [round(float(v), 2) for v in table]}
    dist = getattr(raw, "Distribution", raw)
    const = getattr(dist, "Constant", None)
    return vec_tuple(const) if const is not None else type_name(dist)


def module_state(m: Any) -> Any:
    name = type_name(m)
    dists = {p: distribution_state(getattr(m, p)) for p in ("StartLocation", "StartSize", "StartVelocity", "Lifetime")
             if getattr(m, p, None) is not None}
    if not dists:
        return name
    return {name: dists["StartLocation"] if list(dists) == ["StartLocation"] else dists}


# Run 28: the start location is ~0 and the component sits on the camera's view axis, yet Angel shows top right, so the
# placement must be in the material. Dump each material with its parameters and parent chain.

def material_state(m: Any, depth: int = 0) -> Any:
    if m is None:
        return None
    out: dict[str, Any] = {"name": str(m), "class": type_name(m)}
    for key, prop in (("scalars", "ScalarParameterValues"), ("vectors", "VectorParameterValues"),
                      ("textures", "TextureParameterValues")):
        values = {}
        for p in list(getattr(m, prop, None) or []):
            v = p.ParameterValue
            if hasattr(v, "R"):
                v = (round(float(v.R), 3), round(float(v.G), 3), round(float(v.B), 3), round(float(v.A), 3))
            elif isinstance(v, float):
                v = round(v, 4)
            elif not isinstance(v, (int, bool)):
                v = str(v)
            values[str(p.ParameterName)] = v
        out[key] = values
    parent = getattr(m, "Parent", None)
    if parent is not None and depth < 4:
        out["parent"] = material_state(parent, depth + 1)
    return out


def instance_material(component: Any, param: Any) -> Any:
    for p in list(getattr(component, "InstanceParameters", None) or []):
        if str(p.Name) == str(param):
            return p.Material
    return None


def particle_record(rec: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"template": str(getattr(rec, "Template", None)), "param": str(getattr(rec, "MatParamName", ""))}
    out["component"] = safe_fields(getattr(rec, "Component", None), (
        "Translation", "Rotation", "Scale", "Scale3D", "AbsoluteTranslation", "AbsoluteRotation", "AbsoluteScale",
        "DepthPriorityGroup", "bOnlyOwnerSee"))
    try:
        out["instance"] = material_state(instance_material(getattr(rec, "Component", None), out["param"]))
    except Exception as ex:
        out["instance"] = f"<{type(ex).__name__}: {ex}>"
    emitters = []
    for e in list(getattr(getattr(rec, "Template", None), "Emitters", None) or []):
        lods = list(getattr(e, "LODLevels", None) or [])
        lod = lods[0] if lods else None
        required = getattr(lod, "RequiredModule", None)
        req = safe_fields(required, ("bUseLocalSpace", "ScreenAlignment", "bOrientZAxisTowardCamera"))
        try:
            req["Material"] = material_state(getattr(required, "Material", None))
        except Exception as ex:
            req["Material"] = f"<{type(ex).__name__}: {ex}>"
        emitters.append({"name": str(getattr(e, "EmitterName", "")), "required": req,
                         "modules": [module_state(m) for m in list(getattr(lod, "Modules", None) or [])]})
    out["emitters"] = emitters
    return out


def particle_records(pc: Any) -> list[Any]:
    return list(getattr(pc, "ScreenParticleRecords", None) or [])


def rot_tuple(r: Any) -> tuple[int, int, int]:
    return int(r.Pitch), int(r.Yaw), int(r.Roll)


def view_point(pc: Any) -> tuple[tuple[float, float, float], tuple[int, int, int]]:
    out = pc.GetPlayerViewPoint(unrealsdk.make_struct("Vector"), unrealsdk.make_struct("Rotator"))
    return next(vec_tuple(v) for v in out if hasattr(v, "X")), next(rot_tuple(v) for v in out if hasattr(v, "Pitch"))


def particle_view(pc: Any, component: Any) -> str:
    """Camera, FOV and distance/scale for one watch line: the overlay keeps a fixed angle while distance/scale stays
    constant (~19.3, runs 27-30), so only the FOV can still change where Angel appears."""
    try:
        loc, rot = view_point(pc)
    except Exception as ex:
        return f"<{type(ex).__name__}>"
    try:
        fov: Any = round(float(pc.GetFOVAngle()), 1)
    except Exception as ex:
        fov = f"<{type(ex).__name__}>"
    t, scale = vec_tuple(component.Translation), float(component.Scale)
    ratio = round(math.dist(t, loc) / scale, 2) if scale else None
    return f"{loc} rotation {rot}, fov {fov}, distance/scale {ratio}"


def on_screen_particle(pc: Any, name: str) -> None:
    try:
        log(f"screen particle ({name}): {[particle_record(r) for r in particle_records(pc)]}")
        S.sp_until, S.sp_next = time.time() + VOG_WATCH_SECONDS, time.time() + 1.0
    except Exception as ex:  # a diagnostic must never break the call
        warn_once("sp:" + type(ex).__name__, f"screen particle inspection failed ({type(ex).__name__}: {ex})")


def watch_particles(pc: Any, now: float) -> None:
    S.sp_next = now + 1.0
    try:
        for rec in particle_records(pc):
            c = rec.Component
            log(f"screen particle at {vec_tuple(c.Translation)} rotation {rot_tuple(c.Rotation)}, "
                f"camera at {particle_view(pc, c)}")
    except Exception as ex:
        S.sp_until = 0.0
        warn_once("spwatch:" + type(ex).__name__, f"screen particle watch failed ({type(ex).__name__}: {ex})")


# Runs 27-30: the VoG particle (fx_PostProcess.VoG.part_VoG_Pulse; part_VoG_SimpleFade is 20 x 10) is a 17.76 x 10
# overlay whose component the native keeps on the camera's view axis, scaled with its distance (local space: X forward,
# Y right, Z up). Classic shows it top right although Angel is centred in every video frame (all 14 PostLook videos
# measured). "Angel position" = Centered shifts the overlay left by VOG_SHIFT of its width before the effect starts
# (the emitter's start location, cooked into StartLocation.LookupTable as [min value, max value, then
# LookupTableChunkSize floats per entry: XYZ, or min XYZ + max XYZ]); Classic restores the authored values.
VOG_ORIGINAL: dict[tuple[str, int, int], list[float]] = {}
VOG_WIDTH = 17.76                      # Main_VOG's StartSize X (run 29), if the template has no size table
VOG_SHIFT = 0.28                       # 0.25 moved her from ~75% to ~53% across (run 30): 0.28 centres her


def overlay_width(template: Any) -> float:
    for e in list(getattr(template, "Emitters", None) or []):
        for lod in list(getattr(e, "LODLevels", None) or [])[:1]:
            for m in list(getattr(lod, "Modules", None) or []):
                table = getattr(getattr(m, "StartSize", None), "LookupTable", None)
                if table is not None and len(table) > 2 and float(table[2]) > 0:
                    return float(table[2])
    return VOG_WIDTH


def vog_location_tables(template: Any) -> list[tuple[tuple[str, int, int], Any, Any, Any]]:
    out = []
    for ei, e in enumerate(list(getattr(template, "Emitters", None) or [])):
        for lod in list(getattr(e, "LODLevels", None) or [])[:1]:
            for mi, m in enumerate(list(getattr(lod, "Modules", None) or [])):
                start = getattr(m, "StartLocation", None)
                table = getattr(start, "LookupTable", None)
                if table is not None:
                    out.append(((str(template), ei, mi), m, start, table))
    return out


def place_vog_particle(template: Any) -> None:
    if "vog" not in str(template).lower():
        return
    shift = round(VOG_SHIFT * overlay_width(template), 2)
    for key, module, start, table in vog_location_tables(template):
        chunk = int(getattr(start, "LookupTableChunkSize", 3) or 3)
        if opt_angel_position.value == "Centered":
            if key in VOG_ORIGINAL:
                continue
            VOG_ORIGINAL[key] = [float(v) for v in table]
            sideways = [i for k in range(2, len(table) - 1, chunk) for i in (k + 1, k + 4) if i < min(k + chunk, len(table))]
            for i in sideways:
                table[i] = round(float(table[i]) - shift, 4)
            log(f"Angel's video moved left by {shift}: start location {VOG_ORIGINAL[key]} -> {[float(v) for v in table]}")
        elif key in VOG_ORIGINAL:
            for i, v in enumerate(VOG_ORIGINAL.pop(key)):
                table[i] = v
            log("Angel's video back to its classic place")
        module.StartLocation = start            # in case the struct came back as a copy


@hook("WillowGame.WillowPlayerController:ShowScreenParticle", Type.PRE)
def on_show_screen_particle_pre(obj: Any, args: Any, ret: Any, func: Any) -> None:
    try:
        place_vog_particle(getattr(args, "Template", None))
    except Exception as ex:  # an experiment must never break the effect
        warn_once("vogplace:" + type(ex).__name__, f"Angel placement failed ({type(ex).__name__}: {ex})")


SEEN_PARTICLES: set[str] = set()     # ShowScreenParticle also runs for repeating effects (burning, shock): log each once


@hook("WillowGame.WillowPlayerController:ShowScreenParticle", Type.POST)
def on_show_screen_particle(obj: Any, args: Any, ret: Any, func: Any) -> None:
    template = str(getattr(args, "Template", None))
    if template not in SEEN_PARTICLES:
        SEEN_PARTICLES.add(template)
        on_screen_particle(obj, "ShowScreenParticle")


@hook("WillowGame.WillowPlayerController:SetUpVoGScreenParticle", Type.POST)
def on_vog_screen_particle(obj: Any, args: Any, ret: Any, func: Any) -> None:
    on_screen_particle(obj, "SetUpVoGScreenParticle")


# Autosave diagnostic (v0.14.8, PHASE3 3ax): WillowHUD draws SavingMat natively on the canvas, above the minimap, at a
# position fixed in native code (no position property in either edition). Its plain properties SaveStartTime,
# SaveDuration and SavingMaterialScale are readable, so log how a save drives them before deciding on a fix.

def save_state(pc: Any) -> Any:
    hud = getattr(pc, "myHUD", None)
    if hud is None:
        return None
    out: dict[str, Any] = {}
    for name in SAVE_FIELDS:
        try:
            v = getattr(hud, name)
        except Exception:
            continue
        out[name] = round(float(v), 3) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)
    return out or None


def watch_save(pc: Any) -> None:
    try:
        state = save_state(pc)
    except Exception as ex:  # a diagnostic must never break the tick
        warn_once("save:" + type(ex).__name__, f"save indicator check failed ({type(ex).__name__}: {ex})")
        return
    if state != S.save_state:
        S.save_state = state
        try:
            world_time: Any = round(float(pc.WorldInfo.TimeSeconds), 2)
        except Exception as ex:
            world_time = f"<{type(ex).__name__}>"
        log(f"save indicator: {state}, 'world_time': {world_time}")


@hook("WillowGame.WillowHUD:NotifySavingStarted", Type.PRE)
def on_saving_started(obj: Any, args: Any, ret: Any, func: Any) -> None:
    log("save started (NotifySavingStarted)")


@hook("WillowGame.WillowHUD:NotifySavingComplete", Type.PRE)
def on_saving_complete(obj: Any, args: Any, ret: Any, func: Any) -> None:
    log(f"save complete (NotifySavingComplete, {getattr(args, 'InSaveDuration', '?')} s)")


def apply_layout_now(movie: Any) -> None:
    layout(movie)
    place_static(movie)          # zoom changes move every icon relative to the art
    movie.SetVariableBool("p1.bearing._visible", not opt_hide_compass.value)


def mark_layout_dirty(*_: Any) -> None:
    # Applied on the next tick, so the option already holds its new value.
    S.layout_dirty = True


for _opt in (opt_position, opt_dock_size, opt_scale, opt_margin_x, opt_margin_y, opt_zoom, opt_icon_size,
             opt_hide_compass):
    _opt.on_change_while_enabled = mark_layout_dirty
opt_givers.on_change_while_enabled = lambda *_: rebuild()
opt_objective_tint.on_change_while_enabled = lambda *_: rebuild()     # deferred: runs after the value is set

opt_rebuild = ButtonOption("Refresh map markers", on_press=lambda _: rebuild(),
                           description="Re-collect landmarks and objectives and refit the zoom (same as F8).")
opt_rebuild_movie = ButtonOption("Rebuild HUD movie from game files", on_press=lambda _: remake_movie(rebuild=True),
                                 description="Build the minimap's HUD movie from your game files again (for "
                                             "example after installing GOTY Enhanced). Takes effect from the next "
                                             "level load.")


@hook("Engine.WorldInfo:IsMenuLevel", Type.POST)
def on_menu_level(obj: Any, args: Any, ret: Any, func: Any) -> None:
    """Another HUD mod (Extended UI) swaps the template in its own IsMenuLevel PRE hook; merge after it."""
    if not Redirect.enabled:
        return
    try:
        reconcile()
    except Exception as ex:  # never let a minimap error break the game loop
        warn_once("menu:" + type(ex).__name__, f"HUD template check failed ({type(ex).__name__}: {ex})")


def on_enable() -> None:
    Redirect.enabled = True
    redirect()
    S.reset()       # re-check the current HUD on the next tick


def on_disable() -> None:
    Redirect.enabled = False
    teardown()
    unredirect()


mod = build_mod(options=[opt_position, opt_dock_size, opt_scale, opt_margin_x, opt_margin_y, opt_zoom, opt_zoom_mode,
                         opt_icon_size,
                         opt_rotate, opt_rotation_offset, opt_threats, opt_threat_range, opt_givers, opt_objective_tint,
                         opt_hide_compass,
                         opt_enhanced_art, opt_angel_position, opt_rebuild, opt_rebuild_movie, opt_enhanced_folder])
BASE_DESCRIPTION = getattr(mod, "description", "") or ""
