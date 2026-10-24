"""Classic Minimap: an Enhanced-style minimap for Borderlands GOTY (classic, x86).

Doc citations below (PHASE3 3f, PLAN_V08 3, ENHANCED_NATIVE.md 4, ...) refer to files under docs/; start at
docs/PROGRESS.md.

Needs GfxHUD_Minimap.upk (built by tools/swfbuild.py + tools/upkpatch.py) in WillowGame/CookedPC: the
stock HUD movie plus the `bl1mm_map` clip and the root functions this mod calls.

Why a separate package: classic WillowGame.u carries its own cooked copy of GfxHUD.FlashMovie.HUD and the
hud_instance template, loaded at startup, so GfxHUD.upk on disk is never read. On enable the mod loads
GfxHUD_Minimap and points the template's MovieInfo at its movie; HUDs spawned afterwards (any level load)
use it. Disable restores the original (PHASE3.md 3d).

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
  * objective diamonds are tinted by the tracked mission's status (classic art has no turnin/newmission);
  * docked like Enhanced (PLAN_V07.md 3): the map takes Enhanced's p1-space placement, sheared like the other
    right-column HUD elements (transform.matrix, with an unsheared fallback), and while it shows, ECHO, the
    mission title and the checklist move to Enhanced's positions (its p<N>.UpdateEchoPosition);
  * rebuilds (mission/objective/area changes) swap the markers in place, without hiding the map;
  * Enhanced's zoom and icon size relative to the window, edge indicators for north and off-window
    objectives, and mission givers: "!" where classic's own GetEligibleMissions says a mission can start,
    the turn-in icon where GetRedeemableMissions says one can be handed in (PLAN_V08.md).
"""
import json
import math
import time
from pathlib import Path
from typing import Any

import unrealsdk
from mods_base import (SETTINGS_DIR, BoolOption, ButtonOption, ObjectFlags, SliderOption, SpinnerOption, build_mod,
                       get_pc, hook, keybind)
from unrealsdk.hooks import Type
from unrealsdk.unreal import WeakPointer

__version__ = "0.8.1"


STAGE_W = 1280.0                       # classic HUD stage is 1280x720
MASK_RIGHT, MASK_TOP = 885.0, 72.0     # mask's right/top edge in the map clip's local space
MASK_LEFT, MASK_W, MASK_H = 64.25, 820.75, 527.0   # map.mask in the clip (ViewSize logged by the helper)
ENH_WINDOW_W = 220.0                   # Enhanced minimap window width in its clip (edge test |x| > 110)
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
# Enhanced's minimap zoom: extInitComplete picks Scales[3] = 100 then AnalogScale(1.0) adds ZoomSpeedFactor 8
# (class defaults, tools/upkprops.py) -> its art at 108% in a window ENH_WINDOW_W wide. The art is the same
# size as ours, so relative to our window: 108 * MASK_W / ENH_WINDOW_W (~403%) is "100%".
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
STATUS_TINT = {MS_NOT_STARTED: 0x50E050, MS_READY_TO_TURN_IN: 0xFFC420}   # newmission green, turnin gold
LANDMARK_CLIP = "map.maps.landmarks"   # icon template clip (frames objective .. questionmark, turnin, newmission)
RECORD_KINDS = {"FloatProperty", "IntProperty", "BoolProperty", "ByteProperty", "StrProperty", "NameProperty",
                "StructProperty", "ObjectProperty"}
ANCHOR_LOG: Path = SETTINGS_DIR / "classic_minimap_anchors.jsonl"
MOVIE_PACKAGE = "GfxHUD_Minimap"
MOVIE_PATH = "GfxHUD_Minimap.FlashMovie.HUD"
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
opt_icon_size = SliderOption("Icon size (%)", 100, 50, 200,
                             description="Landmark, player and enemy icon size; 100% matches Enhanced.")
opt_givers = BoolOption("Show mission givers", True,
                        description="Show ! where a new mission can be picked up and the turn-in icon where "
                                    "a finished mission can be handed in, like Enhanced.")
opt_rotate = BoolOption("Rotate with player", False, description="Rotate the map so you always face up.")
opt_rotation_offset = SpinnerOption("Rotation offset", "0", ["0", "90", "180", "270"], is_hidden=True,
                                    description="Correction if the player arrow doesn't point up when rotating.")
opt_threats = BoolOption("Show enemies", True, description="Show enemies the compass radar tracks as red dots.")
opt_threat_range = SliderOption("Enemy range (m)", 0, 0, 200,
                                description="Only show enemies this close. 0 = no limit, like Enhanced.")
opt_hide_compass = BoolOption("Hide compass", False, description="Hide the classic compass strip.")


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
        self.rebuild_pending = False       # F8 / status menu closed: rebuild in place on the next tick
        # docking (PLAN_V07 3): layout name when docked, p1 signature it was computed for, HUD column state
        self.dock: Any = None
        self.p1_sig: Any = None
        self.dock_mode: Any = None
        self.hud_on = False
        self.next_dock_check = 0.0
        # copied at collection time (no native references)
        self.anchor: dict[str, Any] = {}
        self.sources: list[tuple[str, str, float, float, float, bool]] = []
        self.tint: Any = None
        self.givers: list[Any] = []        # WeakPointers to interactive objects with mission directives
        # computed once the zone frame is on stage
        self.xf: tuple[float, ...] = ()
        self.cs: tuple[float, float] = (1.0, 1.0)
        self.frame = 0.0
        self.marks: list[tuple[str, str, float, float, float, Any]] = []


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
    s = opt_scale.value / 100.0
    x = STAGE_W - opt_margin_x.value - MASK_RIGHT * s
    y = opt_margin_y.value - MASK_TOP * s
    cmd(movie, "create", x, y, float(opt_scale.value))
    v = get_num(movie, "map._x")          # Infinity when _root.map doesn't exist
    if not (isinstance(v, float) and math.isfinite(v)):
        return False
    dock(movie, x, y, s)
    return True


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
    """Stage matrix for _root.map: our mask scaled to Enhanced's window, Enhanced's p1-space matrix
    (shear included) centred on its placement, then p1's own transform (unsheared: x/y + scale)."""
    a, b, c, d, etx, ety = lay["map"]
    k = ENH_WINDOW_W / MASK_W * opt_dock_size.value / 100.0
    la, lb, lc, ld = k * a, k * b, k * c, k * d
    cx, cy = MASK_LEFT + MASK_W / 2.0, MASK_TOP + MASK_H / 2.0
    tx, ty = etx - (la * cx + lc * cy), ety - (lb * cx + ld * cy)
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
        s = opt_scale.value / 100.0
        dock(movie, STAGE_W - opt_margin_x.value - MASK_RIGHT * s, opt_margin_y.value - MASK_TOP * s, s)


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
    original: Any = None
    movie_info: Any = None


def find(cls: str, path: str) -> Any:
    try:
        return unrealsdk.find_object(cls, path) or None
    except Exception:
        return None


def redirect() -> bool:
    """Point the HUD movie template at GfxHUD_Minimap's movie, loading the package if needed."""
    tmpl = find("WillowHUDGFxMovie", TEMPLATE_PATH)
    if tmpl is None:
        log(f"HUD template {TEMPLATE_PATH} not found; minimap idle")
        return False
    info = find("GFxMovieInfo", MOVIE_PATH)
    if info is None:
        try:
            unrealsdk.load_package(MOVIE_PACKAGE)
        except Exception as ex:
            log(f"couldn't load {MOVIE_PACKAGE}.upk ({type(ex).__name__}: {ex})")
        info = find("GFxMovieInfo", MOVIE_PATH)
    if info is None:
        log(f"{MOVIE_PACKAGE}.upk not found in WillowGame/CookedPC; minimap idle")
        return False
    if Redirect.template is None:
        Redirect.original = tmpl.MovieInfo
    Redirect.template, Redirect.movie_info = tmpl, info
    tmpl.MovieInfo = info
    log(f"HUD template now uses {MOVIE_PATH} (was {Redirect.original})")
    return True


def unredirect() -> None:
    if Redirect.template is not None and Redirect.original is not None:
        Redirect.template.MovieInfo = Redirect.original
    Redirect.template = Redirect.original = Redirect.movie_info = None


def uses_minimap_movie(movie: Any) -> bool:
    try:
        return Redirect.movie_info is not None and movie.MovieInfo == Redirect.movie_info
    except Exception:
        return False


def start(pc: Any, movie: Any) -> None:
    """Attach the map clip, then collect the zone's objects."""
    S.movie = movie
    if not uses_minimap_movie(movie):
        # This HUD was spawned from the stock movie (before the redirect, or the redirect failed).
        S.phase = "stockhud"
        warn_once("stockhud", f"current HUD uses {movie.MovieInfo}, not {MOVIE_PATH}: "
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
        S.sources = object_sources(helper)
        S.givers = find_givers() if opt_givers.value else []
        S.sources += [(LANDMARK_CLIP, frame, *loc, False) for _, frame, loc in giver_states(pc)]
        # Baseline for change detection = what this collection was built from. Recording it lazily at the
        # next check would miss an objective that moved in between and keep the stale marker.
        try:
            S.objective_key = objective_key(pc)
        except Exception:
            S.objective_key = None
        S.tint = objective_tint(pc)
        helper.InitMapFrame(movie)        # native: map.maps.gotoAndStop(<zone>) or InitDLC(<frame>, <pkg>)
    finally:
        release(helper)
    S.anchor_attempts = 0
    return True


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
    S.frame = get_num(movie, "map.maps._currentframe")
    S.marks = []
    for clip, frame, x, y, z, waypoint in S.sources:
        u, v = to_map(x, y, z)
        if math.isfinite(u) and math.isfinite(v):
            S.marks.append((clip, frame, u, v, 0.0, S.tint if waypoint else None))
    record_anchor(w, h)
    S.phase = "running"
    place_static(movie)
    S.next_threats = 0.0                  # dots were cleared with the icons: redraw on this tick
    if not in_place:
        S.shown = None                    # the next tick decides visibility (hidden_reason)
    movie.SetVariableBool("p1.bearing._visible", not opt_hide_compass.value)
    log(f"map ready: {S.anchor['MapFrame']} (frame {S.frame:g}), {len(S.marks)} markers")
    return True


def zoom_percent() -> float:
    """themap scale for the chosen zoom, relative to the window like Enhanced's 108% (PLAN_V08 1)."""
    return ENH_ZOOM * MASK_W / ENH_WINDOW_W * float(opt_zoom.value.rstrip("%")) / 100.0


def icon_percent() -> float:
    """Icon scale: Enhanced draws icons at its map clip's 0.7, i.e. ENH_WINDOW_W units per window; ours sit
    in the unscaled maps of a MASK_W window."""
    return MASK_W / ENH_WINDOW_W * opt_icon_size.value


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


def objective_tint(pc: Any) -> Any:
    """Enhanced picks turnin/newmission icons from mission status (FUN_14138d240); classic's art has
    neither frame, so the objective diamond is tinted instead (None = stock colour)."""
    try:
        return STATUS_TINT.get(mission_status(pc, tracked_mission()))
    except Exception as ex:
        warn_once("status:" + type(ex).__name__, f"mission status unavailable ({type(ex).__name__}: {ex})")
        return None


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
    if S.rebuild_pending:
        S.rebuild_pending = False
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


@hook("WillowGame.WillowPlayerController:PlayerTick", Type.PRE)
def on_player_tick(obj: Any, args: Any, ret: Any, func: Any) -> None:
    if obj != get_pc():
        return
    try:
        tick(obj)
    except Exception as ex:  # never let a minimap error break the game loop
        warn_once("tick:" + type(ex).__name__, f"tick error ({type(ex).__name__}: {ex}); resetting")
        S.reset()


def rebuild() -> None:
    """Re-collect landmarks/objectives on the next tick: in place while the map runs (no blank map);
    otherwise start over."""
    if S.phase == "running":
        S.rebuild_pending = True
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
                            "hud.MovieInfo": str(movie.MovieInfo) if movie is not None else None}
    if movie is not None:
        info.update(describe(movie))
    info.update(anchor=S.anchor.get("name"), map_frame=S.anchor.get("MapFrame"), anchor_attempts=S.anchor_attempts,
                markers=len(S.marks), tint=S.tint, givers=len(S.givers),
                giver_icons=[f for _, f, _ in giver_states(pc)] if pc is not None else None,
                zoom=zoom_percent(), icon_scale=icon_percent(),
                captured_frame=S.frame, CoordScale=S.cs, Transform=S.xf,
                threat_source=S.threat_source, radar_empty=S.radar_empty, radar_misses=S.radar_misses,
                position=opt_position.value, dock=S.dock, dock_mode=S.dock_mode, hud_shifted=S.hud_on,
                p1=S.p1_sig)
    if movie is not None:
        info.update(dock_b=get_num(movie, "mmDockB"), echo_x=get_num(movie, "p1.echo._x"),
                    echo_x0=get_num(movie, "mmEchoX0"))
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


@hook("WillowGame.StatusMenuExGFxMovie:OnClose", Type.POST)
def on_status_menu_close(obj: Any, args: Any, ret: Any, func: Any) -> None:
    rebuild()  # missions/waypoints may have changed while the menu was open


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

opt_rebuild = ButtonOption("Rebuild now", on_press=lambda _: rebuild(),
                           description="Re-collect landmarks and objectives.")


def on_enable() -> None:
    redirect()
    S.reset()       # re-check the current HUD on the next tick


def on_disable() -> None:
    teardown()
    unredirect()


mod = build_mod(options=[opt_position, opt_dock_size, opt_scale, opt_margin_x, opt_margin_y, opt_zoom, opt_icon_size,
                         opt_rotate, opt_rotation_offset, opt_threats, opt_threat_range, opt_givers, opt_hide_compass,
                         opt_rebuild])
