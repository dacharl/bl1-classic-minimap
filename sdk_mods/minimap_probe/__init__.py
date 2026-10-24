"""Phase 0 probe for the classic BL1 minimap (v0.2).

Records runtime data that static analysis could not recover (the native code is SteamStub-encrypted).

Install: drop minimap_probe.sdkmod (built by tools/build_sdkmod.py) into <Borderlands>/sdk_mods,
         restart, enable "Minimap Probe" in MODS.
Output:  <Borderlands>/sdk_mods/settings/minimap_probe_log.jsonl (one JSON object per line).
         A .sdkmod is a read-only zip, so the log can't live next to __file__.

  * automatic: the status-menu map is hooked where it actually refreshes - SetupMapPage and
    extInitComplete (map opened) and PanMap (throttled to 2/s). Each record holds the full helper
    state plus the Flash-side view (map.maps._x/_y, mask and art sizes, icon positions).
  * F9:  HUD access test - read/write HUD movie variables, construct (or reuse) a WillowGFxHelperMap
         on the HUD movie and run its script-side Init.
  * F10: run InitMapFrame/InitMapFrameVars/UpdateObjects on the HUD helper, then sample
         UpdateObjects(false) twice a second for 10 s. Walk and turn while it samples.

v0.1 results and what v0.2 adds: see PHASE0.md section 2b.
"""
import json
import time
from pathlib import Path
from typing import Any

import unrealsdk
from mods_base import SETTINGS_DIR, build_mod, get_pc, hook, keybind
from unrealsdk.hooks import Type

__version__ = "0.2.0"

LOG: Path = SETTINGS_DIR / "minimap_probe_log.jsonl"

SAMPLE_SECONDS = 10.0
SAMPLE_INTERVAL = 0.5
PAN_LOG_INTERVAL = 0.5

_hud_helper: Any = None
_sample_until = 0.0
_next_sample = 0.0
_next_pan_log = 0.0


def log(kind: str, **data: Any) -> None:
    rec = {"t": time.time(), "kind": kind, **data}
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    print(f"[minimap_probe] {kind}: {json.dumps(data, default=str)[:300]}")


def vec(v: Any) -> Any:
    try:
        return [v.X, v.Y] + ([v.Z] if hasattr(v, "Z") else [])
    except Exception:
        return str(v)


def safe(fn: Any) -> Any:
    try:
        return fn()
    except Exception as ex:
        return f"<{type(ex).__name__}: {ex}>"


def apply_transform(helper: Any, loc: Any) -> Any:
    """World location -> map space through helper.Transform, row-vector convention ([x y z 1] * M)."""
    m = helper.Transform
    x, y, z = loc.X, loc.Y, loc.Z
    return [x * m.XPlane.X + y * m.YPlane.X + z * m.ZPlane.X + m.WPlane.X,
            x * m.XPlane.Y + y * m.YPlane.Y + z * m.ZPlane.Y + m.WPlane.Y]


def player_info(helper: Any) -> list[dict[str, Any]]:
    out = []
    for i, o in enumerate(helper.MapObjects):
        if not o.Player:
            continue
        pawn = safe(lambda o=o: o.Player.Pawn)
        out.append({
            "i": i,
            "controller_world": safe(lambda o=o: vec(o.Player.Location)),
            "pawn": str(pawn),
            "pawn_world": safe(lambda p=pawn: vec(p.Location) if p and not isinstance(p, str) else None),
            "pawn_yaw": safe(lambda p=pawn: p.Rotation.Yaw if p and not isinstance(p, str) else None),
            "pawn_uv_via_transform": safe(lambda p=pawn: apply_transform(helper, p.Location)
                                          if p and not isinstance(p, str) else None),
            "transformed": safe(lambda o=o: vec(o.TransformedLocation)),
            "angle": safe(lambda o=o: o.Angle),
            "icon_path": safe(lambda o=o: o.AS_IconPath),
            "dirty": safe(lambda o=o: o.bIsDirty),
        })
    return out


def dump_helper(helper: Any, objects: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in ("ViewSize", "ViewOffset", "ClipSize", "DesiredCenter", "CoordScale", "AnchorSize"):
        out[name] = safe(lambda n=name: vec(getattr(helper, n)))
    for name in ("Transform", "CurrScaleVal", "CurrentScaleIdx", "bCenterDirty", "bDesiredCenterDirty",
                 "bMapFrameDirty", "bSizesInitialized", "bPlayersDirty", "ViewBorder", "PanRate"):
        out[name] = safe(lambda n=name: str(getattr(helper, n)))
    out["players"] = player_info(helper)
    if not objects:
        return out

    out["Anchor"] = safe(lambda: str(helper.Anchor))
    out["AnchorLocation"] = safe(lambda: vec(helper.Anchor.Location) if helper.Anchor else None)
    out["Scales"] = safe(lambda: list(helper.Scales))
    objs = []
    for i, o in enumerate(helper.MapObjects):
        actor = o.Landmark or o.ClientInteractiveObject
        if o.Player:
            continue  # covered by "players"
        objs.append({
            "i": i,
            "kind": "landmark" if o.Landmark else "io" if o.ClientInteractiveObject else "other",
            "actor": safe(lambda a=actor: str(a)),
            "world": safe(lambda a=actor: vec(a.Location) if a else None),
            "uv_via_transform": safe(lambda a=actor: apply_transform(helper, a.Location) if a else None),
            "transformed": safe(lambda o=o: vec(o.TransformedLocation)),
            "clip_frame": safe(lambda o=o: o.AS_IconClipFrame),
            "icon_path": safe(lambda o=o: o.AS_IconPath),
        })
    out["MapObjects"] = objs
    return out


def flash_state(movie: Any, helper: Any) -> dict[str, Any]:
    out = {
        p: safe(lambda p=p: movie.GetVariableNumber(p))
        for p in ("map.maps._x", "map.maps._y", "map.maps._xscale", "map.maps._yscale", "map.maps._rotation",
                  "map.maps.themap._x", "map.maps.themap._y", "map.maps.themap._width", "map.maps.themap._height",
                  "map.mask._width", "map.mask._height", "map.mask._x", "map.mask._y")
    }
    out["map.maps._currentframe"] = safe(lambda: movie.GetVariableNumber("map.maps._currentframe"))
    icons = {}
    for o in helper.MapObjects:
        path = safe(lambda o=o: o.AS_IconPath)
        if path and not str(path).startswith("<"):
            icons[path] = [safe(lambda p=path: movie.GetVariableNumber(p + "._x")),
                           safe(lambda p=path: movie.GetVariableNumber(p + "._y")),
                           safe(lambda p=path: movie.GetVariableNumber(p + "._rotation"))]
    out["icons"] = icons
    return out


def log_full_map(kind: str, movie: Any, objects: bool = True, **extra: Any) -> None:
    helper = movie.MapHelper
    if helper is None:
        log(kind, error="MapHelper is None", **extra)
        return
    log(kind, **extra, **dump_helper(helper, objects), flash=flash_state(movie, helper))


@hook("WillowGame.StatusMenuExGFxMovie:SetupMapPage", Type.POST)
def on_setup_map_page(obj: Any, args: Any, ret: Any, func: Any) -> None:
    log_full_map("full_map_setup", obj)


@hook("WillowGame.StatusMenuExGFxMovie:extInitComplete", Type.POST)
def on_full_map_init_complete(obj: Any, args: Any, ret: Any, func: Any) -> None:
    log_full_map("full_map_init_complete", obj)


@hook("WillowGame.StatusMenuExGFxMovie:PanMap", Type.POST)
def on_pan_map(obj: Any, args: Any, ret: Any, func: Any) -> None:
    global _next_pan_log
    now = time.time()
    if now < _next_pan_log:
        return
    _next_pan_log = now + PAN_LOG_INTERVAL
    log_full_map("full_map_pan", obj, objects=False, pan=[args.X, args.Y])


@hook("WillowGame.WillowHUD:PostRender", Type.PRE)
def on_hud_post_render(obj: Any, args: Any, ret: Any, func: Any) -> None:
    global _next_sample
    now = time.time()
    if _hud_helper is None or now > _sample_until or now < _next_sample:
        return
    _next_sample = now + SAMPLE_INTERVAL
    safe(lambda: _hud_helper.UpdateObjects(False))
    log("hud_sample", **dump_helper(_hud_helper, objects=False))


@keybind("Probe HUD access", "F9")
def probe_hud() -> None:
    global _hud_helper
    pc = get_pc()
    hud = pc.myHUD
    movie = safe(lambda: hud.GetHUDMovie())
    log("hud", version=__version__, pc=str(pc), hud=str(hud), movie=str(movie))
    if not movie or isinstance(movie, str):
        return

    # GFx read/write on a path the classic native already writes (compass strip).
    before = safe(lambda: movie.GetVariableBool("p1.bearing._visible"))
    safe(lambda: movie.SetVariableBool("p1.bearing._visible", not before))
    after = safe(lambda: movie.GetVariableBool("p1.bearing._visible"))
    safe(lambda: movie.SetVariableBool("p1.bearing._visible", before))
    log("gfx_rw", before=before, after_toggle=after,
        has_map_clip=safe(lambda: movie.GetVariableNumber("map._width")))

    # Reuse the helper while the HUD movie is the same one; a new movie (level change) needs a new helper.
    if _hud_helper is not None and safe(lambda: _hud_helper.Outer) == movie:
        log("construct", helper=str(_hud_helper), reused=True)
    else:
        _hud_helper = safe(lambda: unrealsdk.construct_object("WillowGFxHelperMap", movie))
        log("construct", helper=str(_hud_helper), reused=False)
        if isinstance(_hud_helper, str):
            _hud_helper = None
            return
    log("init", result=str(safe(lambda: _hud_helper.Init(pc))))
    log("hud_helper_after_init", **dump_helper(_hud_helper))


@keybind("Probe native calls + sample", "F10")
def probe_natives() -> None:
    global _sample_until, _next_sample
    if _hud_helper is None:
        log("natives", error="press F9 first")
        return
    movie = get_pc().myHUD.GetHUDMovie()
    log("natives_begin")
    log("InitMapFrame", ret=str(safe(lambda: _hud_helper.InitMapFrame(movie))))
    log("InitMapFrameVars", ret=str(safe(lambda: _hud_helper.InitMapFrameVars(movie))))
    log("UpdateObjects", ret=str(safe(lambda: _hud_helper.UpdateObjects(False))))
    log("hud_helper_after_natives", **dump_helper(_hud_helper))
    _sample_until = time.time() + SAMPLE_SECONDS
    _next_sample = 0.0
    log("sampling", seconds=SAMPLE_SECONDS, interval=SAMPLE_INTERVAL, note="walk and turn now")


def on_enable() -> None:
    log("session", version=__version__)


mod = build_mod()
