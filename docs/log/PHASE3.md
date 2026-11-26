# Phase 3: Classic Minimap SDK mod

Status, 2026-10-23: **written, tested offline, installed in the game.** Not yet seen running in game.

## 1. What's installed

| File in `steamapps\common\Borderlands` | Source | SHA-256 / size |
|---|---|---|
| `WillowGame\CookedPC\Packages\Interface\GfxHUD.upk` | `dist\phase2\GfxHUD_minimap.upk` (PHASE2) | `ec972e36…7b18` |
| `sdk_mods\classic_minimap.sdkmod` | `dist\classic_minimap.sdkmod`, built from [sdk_mods/classic_minimap](../../sdk_mods/classic_minimap/__init__.py) | 4,638 bytes |

The original HUD package is backed up at `dist\phase1\GfxHUD.orig.upk` (`5c515c3e…3ea88`, verified before the swap).

**Uninstall:**
```bash
cp dist/phase1/GfxHUD.orig.upk "/c/Program Files (x86)/Steam/steamapps/common/Borderlands/WillowGame/CookedPC/Packages/Interface/GfxHUD.upk"
rm "/c/Program Files (x86)/Steam/steamapps/common/Borderlands/sdk_mods/classic_minimap.sdkmod"
```

The `minimap_probe` mod is still installed too. Disable it in MODS, so its F9/F10 don't construct extra helpers.

## 2. How the mod works

- **Tick:** a pre-hook on `WillowGame.WillowPlayerController:PlayerTick` (local player only), throttled to 20 Hz. Any exception is logged once and resets the state; it never propagates into the game loop.
- **Start (new HUD movie, e.g. level load or fast travel):**
  1. `MinimapCreate(x, y, scale)` via `GFxMovie.Invoke`. If it doesn't return `true`, the patched HUD isn't installed, so the mod logs once and stays idle.
  2. `MinimapClear()`.
  3. `construct_object("WillowGFxHelperMap", movie)`, then `Init(pc)`, `ResetMapObjects()`, `InitMapFrame(movie)`.
- **Ready:** poll `map.maps.themap._width` until it's finite and > 0 (a missing path reads `Infinity`). Then run the status menu's `extInitComplete` sequence: `InitMapFrameVars` → `UpdateObjects(true)` → `CurrentScaleIdx` = Zoom option → `ApplyScale` → `ApplyFlash`. If the frame isn't ready after 5 s, start over.
- **Each tick:**
  1. `DesiredCenter` = player `TransformedLocation` (copy-modify-assign).
  2. `UpdateObjects(false)` and `ApplyFlash`.
  3. `MinimapRecenter(rotate, offset)`.
- **Every 0.25 s:** `UpdateThreats("u,v|…")`. It walks `WorldInfo.PawnList` and keeps pawns that are alive (`IsAliveAndWell`), hostile (`Pawn.IsEnemy`), within range, and allowed by the AI's rule engine (`Controller.MyRuleEngine.IsPawnShownInRadarForCurrentState()`, when present). Each is converted with `Transform`/`CoordScale` (PHASE0 §2d).
- **Rebuild:** `F8`, the *Rebuild now* button, or closing the status menu re-collects landmarks and objectives on the next tick.
- **Disable:** `MinimapDestroy()` runs and the compass is shown again.

**Options (MODS → Classic Minimap):**

| Option | Default | Notes |
|---|---|---|
| Size (%) | 28 | scale of the map clip; the window is the full map's 820×527 mask, so about 230×148 px at 28% |
| Right margin / Top margin | 24 / 90 | position on the 1280×720 HUD stage |
| Zoom | 300% | the full map's own levels (400/300/150/100) |
| Rotate with player | off | rotates `maps` by −heading |
| Rotation offset | 0 (hidden) | correction if the arrow art doesn't point up when rotating |
| Show enemies / Enemy range (m) | on / 60 | 1 m ≈ 50 Unreal units |
| Hide compass | off | `p1.bearing._visible` |

## 3. Offline verification

[tools/test_minimap_mod.py](../../tools/test_minimap_mod.py) loads **the real mod** with stub `unrealsdk`/`mods_base`. `movie.Invoke` runs **the built movie's** root functions in the AS2 interpreter. The native helper is emulated with Phase 0's measured behaviour: Fyrestone's `Transform`/`CoordScale`, and icons placed with root `AddLandmark`/`UpdateLandmark` using normalised coordinates. All 11 scenarios pass:

1. The first tick attaches the map in the top-right and constructs the helper on the HUD movie, in the order `Init` → `ResetMapObjects` → `InitMapFrame`.
2. Readiness triggers the `extInitComplete` sequence, and Zoom 300% → `CurrentScaleIdx` 1 → `themap._xscale` 300.
3. `DesiredCenter` follows the player, and the player icon sits exactly at the mask centre.
4. The player moves and stays centred.
5. Enemy dots: only the live, in-range hostile pawn is shown, within 0.05 px of where the native would draw an icon at that spot. *Show enemies* off hides them.
6. Rotation: `maps._rotation` = −heading, and the player stays centred.
7. Option changes apply on the next tick (size, zoom, compass).
8. Rebuild starts over with a new helper.
9. A new HUD movie (level change) gets a fresh start.
10. An unpatched HUD makes the mod idle, with one warning and no helper.
11. Disable removes the map and restores the compass.

## 3b. First in-game run (v0.1.0): nothing showed

`unrealsdk.log` showed `[Classic Minimap] patched GfxHUD.upk not found (MinimapCreate is missing); minimap idle` at 00:12:06, 4 s after the mod was enabled, with no tick errors. So `PlayerTick` reached the hook, but `MinimapCreate` didn't return `true`. The installed `GfxHUD.upk` was verified as the patched one (`ec972e36…`). v0.1.0 then gave up on that HUD movie for the session and only logged once, so later attempts in game were invisible.

The likely cause is that the first call came before the HUD movie had run its frame-1 script (root functions not defined yet), possibly at the main menu. The log couldn't tell that apart from an `attachMovie` failure.

**v0.1.1 changes:**
- **Only start in game:** it starts only when the player has a pawn.
- **Retry instead of giving up:** a failed `MinimapCreate` retries every 1 s, up to 60 times.
- **Diagnostics:** on attempts 1, 5, 20 and 60 it logs what `Invoke` returned, whether the patched root functions exist (`UpdateThreats('')` → `Type=4 B=True`), whether `_root.map` exists (`map._x`, where `inf` means missing) and the stock `p1._x`.
- **F7:** writes a diagnostics line on demand: phase, attempts, helper sizes, map frame.
- **Tests:** three new offline scenarios (no pawn, root functions appearing late, unpatched HUD retry and give-up) all pass.

## 3c. Second in-game run (v0.1.1): `Invoke` returns are garbage, no map attached

The log showed 39 retries with an unchanging state:
```
"UpdateThreats('')": "Type=96 N=2.17e-37 B=False S=''", 'map._x': inf, 'map.mask._width': inf, 'p1._x': 216.05
```

- **Classic `GFxMovie.Invoke` doesn't fill in its return value.** `Type=96` isn't a valid `ASType` (0–4), and `N` is uninitialised memory. This fits the static evidence: classic's own `ApplyScale` calls `Invoke("SetMapScale")` and then reads sizes with `GetVariableNumber`, never using a return, whereas Enhanced added `Invoke`-return helpers (`GetMapWidth`). So v0.1.0/v0.1.1's success test (`MinimapCreate` returned `true`) could never pass. (The native helper's own calls do get returns: it stored `AS_IconPath = "_level0.map.maps.player26"` in Phase 0.)
- **`_root.map` didn't exist** (`map._x = inf`) while the stock HUD was up (`p1._x = 216`). Either the root functions never ran, or `attachMovie` failed. The log couldn't tell which.

**v0.1.2 changes (movie + mod):**
- **The mod never reads `Invoke` returns.** Success is "`map._x` is finite". Diagnostics use side effects: `MinimapPing(token)` → `GetVariableString("mmPing") == token` proves the patched root functions run, and `mmCreateMode` reports `attach` / `fallback` / `none`.
- **The movie has a fallback that doesn't need `attachMovie`:** sprite 1200 is also placed on the root timeline as `mmfallback` (depth 600, at (−20000, −20000), checked by decoding the matrix). If `attachMovie` leaves `map` undefined, `MinimapCreate` renames `mmfallback` → `map` (`_name`). `MinimapDestroy` hides it and gives the name back.
- **Tests:** the fake `Invoke` now returns `Type=96` garbage like the game, and the emulated native calls the movie directly. A new scenario covers `attachMovie` failing and the fallback driving the whole minimap. Everything passes.
- **Installed:** `GfxHUD.upk` = `dist\phase2\GfxHUD_minimap.upk` (SHA-256 `f8dce67a…1912`), and `classic_minimap.sdkmod` v0.1.2.

## 3d. Third in-game run (v0.1.2): the game never reads GfxHUD.upk

The log gave `root functions: False` and **`mmfallback._x: inf`**. The fallback is a plain frame-1 timeline placement, so it can't fail the way `attachMovie` can. If it's missing, the running HUD movie isn't the patched one.

**Root cause (Observed):**
- `WillowHUD.PostBeginPlay` spawns the HUD from `PlayerClass.HUDDefinition.HUDMovieDefinition.SpawnPlayerMovie(...)`.
- That `GFxMovieDefinition` is `GfxHUD.Definitions.HUDDefinition`; its `Movie` is the template `GfxHUD.FlashInstances.hud_instance`, whose `MovieInfo` is `GfxHUD.FlashMovie.HUD`.
- **Classic `WillowGame.u` (the cooked script package, loaded at startup) contains all of those objects**: `GfxHUD.FlashMovie.HUD` (442,528 bytes, the same as the stock movie), the 67 `GfxHUD.FlashMovie.*` textures, `HUDDefinition` and `hud_instance`. It's the same seek-free cooking that put `menus_ingame_redux.FlashMovies.status_menu` in there.
- With those objects already in memory, `GfxHUD.upk` on disk is never opened.
- A name-table scan of all 2,927 classic packages found `GfxHUD` only in `WillowGame.u`, `GfxHUD.upk`, `GuidCache.upk`, `d_hud.upk` and `ken_test.upk`. The startup package `W_Startup_INT.upk` and `Loader.umap` don't carry it.

**Correction to PHASE1 §3:** the "HUD looks fine" result with the resized `GfxHUD_sizetest.upk` didn't test relocation. The game never loaded that file. The offline round trip and relocation checks still stand.

**Fix (v0.2.0):** no stock files are modified.
- **New package:** the minimap movie ships as a separate package, `WillowGame\CookedPC\Packages\Interface\GfxHUD_Minimap.upk` (SHA-256 `e14b9b12…80d6`). It's built with `upkpatch.py replace … --new-guid`, so its package GUID (header offset 0x39) differs from `GfxHUD`'s.
- **Enable:** the mod calls `unrealsdk.load_package("GfxHUD_Minimap")` and sets `hud_instance.MovieInfo = GfxHUD_Minimap.FlashMovie.HUD`. Every HUD spawned afterwards (each level or save load) uses the minimap movie.
- **Disable:** restores the original `MovieInfo`.
- **Stale HUD:** a HUD created before the redirect is detected through `movie.MovieInfo`. The mod logs once ("load a save or change area") instead of retrying.
- **Diagnostics:** F7 now also logs `template.MovieInfo` and `hud.MovieInfo`.
- **Stock file restored:** `GfxHUD.upk` is back to the original (`5c515c3e…`).
- **Tests:** offline tests cover the redirect, a missing package, a HUD spawned before the redirect, no double load, and restore on disable. They pass.

**Uninstall (v0.2.0):** delete `sdk_mods\classic_minimap.sdkmod` and `WillowGame\CookedPC\Packages\Interface\GfxHUD_Minimap.upk`.

## 3e. Fourth in-game run (v0.2.0): redirect works, then a GPF in pyunrealsdk

`unrealsdk.log`:
- `HUD template now uses GfxHUD_Minimap.FlashMovie.HUD (was GFxMovieInfo'GfxHUD.FlashMovie.HUD')` (at the main menu);
- `map attached (attach) after 0 retries` (in game), the first time the patched movie ran in game: the redirect works and `attachMovie` works.

Then the game crashed. The minidump (`My Games\Borderlands\WillowGame\Logs\unreal-v4875-2026.10.23-21.11.13.dmp`) shows **access violation `0xC0000005`, read of `0xF3402478`, in `pyunrealsdk.dll + 0x240964`, on the game thread** (the same thread id as the "map attached" line). `Launch.log` is empty.

**Cause (inferred, consistent with every observation):**
- The mod's next call after attaching is `GFxMovie.Invoke("MinimapClear", …)`.
- Classic `Invoke` leaves its `ASValue` return uninitialised (run 2 read back `Type=96`), and `ASValue.S` is an `FString` (pointer + length).
- pyunrealsdk converts that return struct to Python and frees it. A garbage non-null string pointer means a read from or free of a wild address, so it crashes. In run 2 the garbage happened to be harmless.

**Fix (v0.2.1):**
- **No Python code calls `GFxMovie.Invoke`.** The movie gets one more root function, **`MinimapCmd("op~arg~…")`**, which dispatches to `create` / `destroy` / `clear` / `recenter` / `threats` / `ping`.
- **The mod calls it through `WillowGFxMovie.SingleArgInvokeS("MinimapCmd", …)`.** That's a native (flags `0x20401`) with one string parameter and no return value, used 49 times in classic script for root and path calls (e.g. `SingleArgInvokeF("SetPlayerTotalCredits", …)`).
- **The helper's UnrealScript still calls `Invoke` internally** (`ApplyScale` → `SetMapScale`). That path is exercised by the stock status menu on every zoom, and the result never reaches Python.
- **Tests:** the fake `Invoke` now **raises** if the mod calls it. All AS and mod integration scenarios pass.
- **Installed:** `GfxHUD_Minimap.upk` (SHA-256 `f7aacd2d…9d14`, fresh GUID) and `classic_minimap.sdkmod` v0.2.1. Stock `GfxHUD.upk` is unchanged (`5c515c3e…`).

## 3f. Fifth in-game run (v0.2.1): the same GPF, so the real cause is GC

The crash dialog's `History` and the new minidump (`unreal-v4875-2026.10.23-21.17.58.dmp`) show **the same faulting address as run 4, `0x62120964` (`pyunrealsdk.dll + 0x240964`)**, with a different wild read address (`0x8C8D512B`). So removing `Invoke` (3e) didn't touch the crash, and **3e's explanation was wrong**. The `SingleArgInvokeS` change stays anyway, since it avoids reading the uninitialised return.

**What the stack shows:**
- Python frames run `PyEval_EvalFrameDefault` → `Py_LoadAttr_StackRefSteal` → `PyObject_GetMethod` → `PyObject_GetAttr` → pyunrealsdk.
- So the crash is an **attribute read on a UObject**, inside the `PlayerTick` hook (`unrealsdk` hook dispatch, `Borderlands.exe` below).
- It came within seconds of `map attached (attach)` (21:18:28; dump written the same minute).

**Cause:**
- The `WillowGFxHelperMap` is created from Python with `construct_object` and **referenced by nothing in the engine**; the stock game keeps its helper in `StatusMenuGFxMovie.MapHelper`.
- The engine's GC (which runs around level load) frees it. The next `helper.Something` read follows a dangling pointer, which is a wild read whose address changes each run.
- The probe never hit this because F9/F10 used the helper immediately after creating it.

**Fix (v0.2.2):**
- **Keep the helper alive:** construct it with `flags=ObjectFlags.KEEP_ALIVE`, the flag `mods_base` exports for exactly this ("Prevents the object from getting garbage collected"; `0x4000` on Willow games). The SDK's own `willow1_mod_menu` constructs objects the same way.
- **Release it:** the flag is cleared whenever the mod resets (new HUD, rebuild, disable) so old helpers can be collected.
- **Weak reference to the HUD movie:** it's now held through `unrealsdk.unreal.WeakPointer`, so a movie destroyed by a level unload reads as `None` instead of dangling. The new test caught one gap: the reset when the HUD disappears depended on the stale reference. It's fixed.
- **Tests:** offline tests check the helper is `KEEP_ALIVE` while in use and released on rebuild/reset/HUD loss, and that a destroyed movie never gets touched. They pass.
- **Installed:** `classic_minimap.sdkmod` v0.2.2. `GfxHUD_Minimap.upk` is unchanged (`f7aacd2d…`).

## 3g. v0.3.0: research-informed objective refresh

How the earlier steam-deck-scripts research relates to this mod is in [PRIOR_RESEARCH.md](../research/PRIOR_RESEARCH.md). It independently confirms the projection, the append-only `FindObjects`, the slot-ordinal `UpdateObjects` and the clamped `ApplyFlash`, and it had already flagged helper GC lifetime as unresolved after a Deck trial lost transient helpers.

**Change:** every 0.5 s, while running, the mod computes a key: `MissionTracker.ActiveMission` + `TargetWaypointDefinition` + `TurnInWaypointDefinition` + visible `StreamingLevels` (Objective Distance's cache key). If it changes, the mod rebuilds with a **fresh** helper. That avoids appending into the old helper's `MapObjects` and avoids stale slot ordinals.
- The tracker is found with `find_all("MissionTracker")` and cached through a `WeakPointer`. Keys are strings of freshly read objects.
- If the lookup fails, it logs once and the map keeps running, so it can't cause a reset loop.

**Tests:** new offline scenarios cover a mission change → one rebuild (old helper released, new one `KEEP_ALIVE`), no rebuild while the key is unchanged, an area streaming in and out → rebuilds, and a failing lookup → no rebuild and still running. Everything passes.

**Installed:** `classic_minimap.sdkmod` v0.3.0. `GfxHUD_Minimap.upk` is unchanged (`f7aacd2d…`).

## 3h. Run 6 (v0.3.0) → v0.4.0

**Run 6:** no crash. The minimap window was on screen but blank until the full map had been opened, then it showed the whole zone unzoomed.

**Cause:** the first helper initialised before the zone's anchor had streamed in, so it stayed on frame `none`. See [PLAN_DIRECT.md](../plans/PLAN_DIRECT.md).

**v0.4.0** implements PLAN_DIRECT step A: a transient helper gated on the anchor and the real frame, a primitive snapshot, the helper released, and the map drawn from Python every tick. Each capture logs the anchor's fields for step B.

**Installed:** `GfxHUD_Minimap.upk` `19282138…724a` and `classic_minimap.sdkmod` v0.4.0.

## 3i. Run 7 (v0.4.0): working; hide it during the travel tunnel → v0.5.0

**Run 7:**
- The minimap drew Fyrestone at 300%. F7 showed `themap_w = 2338.5` = 779.5 × 3, and 23 markers were captured.
- It also showed during the travel "blue tunnel", when the stock HUD is gone.
- The overlap with the mission text is the saved option `Top margin = 90` from earlier versions. The new default of 20 only applies to fresh settings.

**Enhanced timing (prior research):**
- The decrypted Enhanced native scheduler (steam-deck-scripts phase-2) gates *updates* only: a ready byte plus non-null controller, pawn and replication slots, at a nominal 0.05 s interval. It has **no visibility test**.
- Enhanced's minimap is `p<N>.map`, a child of the player's HUD clip, so it hides whenever the game hides `p1`. Ours is `_root.map`.
- REA couldn't add more here: no native engine is configured, and the exe is SteamStub-encrypted.

**v0.5.0 visibility rule:** checked every tick. Positions keep updating while hidden. The map is hidden when any of these hold:
1. `pc.IsLoadingMoviePlaying()` (the tunnel). This is a native returning a bool, and classic itself defers `SaveGame` and `ShowPauseMenu` on it.
2. `myHUD.bShowHUD` is false, `pc.bCinematicMode`, `pc.bStatusMenuOpen`, or pawn `Health <= 0`. This mirrors `WillowPlayerController.ShowStatusMenu`'s gate.
3. `p1._visible` is false (mirrors Enhanced's parenting).
4. The **live-level set** (persistent + visible streaming) changed less than **3 s** ago. This is the steam-deck-scripts diagnostics collector's ready-context epoch and settle rule; the epoch survives rebuilds, so a mission change doesn't hide the map.

A failing check logs once and never hides the map for good or resets it. Changes are logged as `minimap shown` / `minimap hidden: <reason>`.

**Tests:** new scenarios cover each condition hiding and restoring the map, a level streaming in → hidden through the rebuild and settle → shown, and a failing check → still shown and running. Everything passes. **Installed:** `classic_minimap.sdkmod` v0.5.0; the package is unchanged (`19282138…`).

**Step B data (from run 7's `classic_minimap_anchors.jsonl`):** the anchor carries `MapFrame = 'Arid'`, `DLCMap`, `TextureSizeX/Y = 1024/512`, `DrawScale3D = (58.2003, 233.131, 160.998)` and `Rotation.Yaw = 32`.
- 1024 × 58.2003 = 59,597.1 and 512 × 233.131 = 119,363.1 match the helper `Transform`'s extents.
- sin(32 UU) / extents gives the off-diagonals −2.57e-8 / 5.15e-8, signs included.
- So the helper-free transform is `qX = (c·dx + s·dy)/(TexX·DS3D.X)`, `qY = (−s·dx + c·dy)/(TexY·DS3D.Y)`, with `dx, dy` taken from `anchor.Location` and θ = yaw·2π/65536. That's fitted from one zone; a second zone would confirm it.

## 3j. Run 8 (v0.5.0) → v0.5.1

**Run 8:** mostly working, with two bugs.

1. **The minimap stayed visible over the open status-menu map.** The log shows `visibility check unavailable (AttributeError: 'WillowPlayerPawn' object has no attribute 'Health')`: classic pawns have no `Health` property. The whole visibility function failed open, so *every* gate (tunnel, menu, HUD) stopped applying.
   **Fix:** each gate is checked separately (a broken one logs once and is skipped), and death uses the native `Pawn.IsAliveAndWell()`.
2. **Stale objective marker.** The minimap showed a white waypoint diamond next to the player while the full map showed it by the health station. The snapshot's objective markers are static, and the rebuild key didn't change when an objective moved within the same mission.
   **Fix:** the key now includes the live slots `WillowGameReplicationInfo.ActiveWaypointData[i].WaypointLocation` (reflected in classic: `ActiveWaypointInfo[MAX_ACTIVE_WAYPOINTS]`; these are what the native rereads), rounded to 100 UU. The baseline key is now recorded **at capture**. The test showed that recording it lazily missed changes in the first 0.5 s after a capture.

**Tests:** the fake pawn now has no `Health`, like the game. New scenarios: a broken check doesn't disable the others; an objective moving → rebuild; drift below the grid → no rebuild; a new objective slot → rebuild; objective rebuilds don't trigger the settle hide. Everything passes. **Installed:** `classic_minimap.sdkmod` v0.5.1; the package is unchanged.

## 3k. v0.6.0: Enhanced's native behaviour, from the decomp (ENHANCED_NATIVE.md)

Not yet run in game.

1. **Step B (transform in Python).** The helper now lives for one call only:
   - `Init` runs classic's own collectors (script FindLandmarks; native FindObjects/FindPlayers), then native `InitMapFrame` selects the frame or DLC movie, and the helper is released before the call returns.
   - No `InitMapFrameVars`/`UpdateObjects`, and no helper during the frame wait.
   - The mod copies the anchor's `Location`, `Rotation`, `DrawScale`, `DrawScale3D` and `TextureSize`, plus each record's world position: `bWaypoint` → `CustomObjectLoc`; `ClientInteractiveObject.Location`; `Landmark.Location`; otherwise `CustomObjectLoc`. `Player`/`WPRI` records are skipped.
   - Once the frame is on stage, it computes `Transform` as classic's anchor matrix does (`FUN_0146bd60` + `D3DXMatrixInverse`), and CoordScale from `TextureSize` vs `themap`'s aspect ratio.
   - **Checked against the game:** the Python matrix reproduces the helper's logged Arid `Transform` within 6.5e-8 relative error and CoordScale within 4e-8. The harness asserts this with the logged anchor fields.
2. **Enemy dots from the compass radar:** every `bActive` entry of `GRI.RadarMgr.RemoteDynamicIcons`, as Enhanced's `UpdateThreats` does.
   - "Enemy range" now defaults to 0 (no limit, like Enhanced) and is an optional filter.
   - If the list stays empty for 5 probes (about 10 s) while an enemy is within 30 m, or there is no `RadarMgr`, the mod switches to the old pawn scan for the session.
3. **Objective status:** classic's landmark art (char 1066) has no `turnin`/`newmission` frames, so the objective diamond is tinted instead: gold when the tracked mission is ready to turn in, green when it's not started. The tint goes through `new Color(clip).setRGB` via the new optional 7th field of the movie's `add` command.
   - The status (read from `pc.MissionPlaythroughData[current].MissionList[].Status`) is part of the rebuild key.
4. **Smaller changes:**
   - The anchor log is written once per anchor per session, with the computed Transform.
   - F7 diagnostics now include the threat source, radar count, anchor and tint.

**Tests:**
- The fake helper now builds records with the real `MapObjectData` field names and raises if `UpdateObjects`/`InitMapFrameVars` is called.
- New scenarios: radar dots (active only, unlimited by default, range filter, toggle); empty-radar fallback after the probe limit; no `RadarMgr`; turn-in tint and un-tint; unreadable mission data; anchor logged once; singular anchor (no map, no crash, retried).
- Both suites pass. **Installed:** package `27122605…91e3`, mod `76359758…61ff`. v0.5.1 is backed up in `dist\v051\`.

**Not verified in game:** the radar list's names and that it's populated in single player (the fallback covers it), the `MissionList` element field names (`MissionDef`, `Status`), and a second zone and a DLC zone.

## 3l. Run 9 (v0.6.0) → v0.7.0 (PLAN_V07.md)

**Run 9:** Arid, Skag Gully, T-Bone Junction (DLC3).
- **Working:** radar dots (`radar_active: 1`), the gold turn-in tint, and DLC3's `dlcmap1` frame.
- **Problems:** a stuck diamond and arrow, a blink on every objective rebuild, and the map covering ECHO/Angel and the quest title.

**v0.7.0:**
1. **Source clips:** `MinimapClear` hides `maps.landmarks/players/enemy` (the templates `AddLandmark` duplicates, placed at the `maps` origin on zone frame 2), and the `add` command and `MinimapPlayer` show what they create. This is Enhanced's `Minimap.SetMapFrame` behaviour.
2. **In-place rebuilds:** a mission/objective/area change, F8, or closing the status menu re-collects, and when the zone frame is unchanged, captures in the same tick. `place_static` swaps the icons, and the player icon and threat dots are redrawn in that tick. No `map._visible = false`, no reset. Only a new HUD movie takes the full path.
3. **Dock:** the default "Position: Docked" places `_root.map` at Enhanced's `p1`-space minimap matrix (16:9 E933: 0.698, 0.049, 0, 0.700, 919.4, 73.4; 4:3 E949: …, 708.4, 99.4).
   - Our 820.75×527 mask is scaled to Enhanced's 220-unit window and centred there, then composed with `p1`'s `_x/_y/_xscale/_yscale`, and set via `map.transform.matrix = new flash.geom.Matrix(...)` (new `MinimapDock`, read back).
   - If the runtime ignores it, the dock falls back to unsheared position and scale, `mmDockMode = plain`, logged once.
   - The layout is identified from classic's authored `p1.echo._x` (791.5 = 16:9 sprite 706; 655.5 = 4:3 sprite 722); unknown layouts (split screen) use the Custom placement.
   - Re-dock is checked every 1 s (`p1` moved, or a new `p1` instance after a layout switch).
4. **HUD column:** `MinimapHudShift` records `p1.echo/quest/check1..5` once per `p1` instance (`p1.mmOrig`). While the docked map shows, it applies Enhanced's placements (echo 610/13.1, quest 577/129.1, check 795.9/59.4 + 16.4n at 92%; the 4:3 values likewise), and restores them whenever the map hides and on disable. Only `_x/_y/_xscale/_yscale` change, so the authored shear stays.
5. **Smaller changes:**
   - Floats are sent with 9 significant digits (matrix terms need them).
   - New options: Position (Docked/Custom) and Docked size; the old Size/margins apply to Custom.
   - F7 shows dock, mode, read-back and echo positions.

**Tests:**
- **AS:** hidden templates while copies stay visible (the VM's duplicate now copies `_visible`); dock in matrix mode and in the fallback; HUD record/apply/restore with no drift.
- **Mod:** fake `p1` with the classic transform and column.
  - **Dock:** shear ratio, scale, and the mask centre landing on Enhanced's spot; size 120%; Custom (no leftover shear, column restored); 4:3 layout switch and back; no-transform fallback.
  - **Column:** follows show/hide; restored on disable.
  - **Rebuild:** no hide, markers swapped in the same tick.
- Both pass.

**Installed:** package `4816400f…748e`, mod `c1574b81…bff0`. v0.6.0 is backed up in `dist\v060\`.

## 3m. Run 10 (v0.7.0) → v0.8.0 (PLAN_V08.md)

**Run 10:** T-Bone correct; Skag Gully waypoints and ECHO placement correct. Enhanced footage shows a closer zoom, edge indicators, and "!" givers.

**v0.8.0:**
1. **Zoom:**
   - "Zoom (vs Enhanced)" 100% = Enhanced's 108% art scale (`Scales[3]` 100 + `AnalogScale(1.0)` × `ZoomSpeedFactor` 8; the art is the same size in both editions), relative to the window: 108 × 820.75/220 ≈ 403%.
   - Icons and threat dots at 820.75/220 × "Icon size", because Enhanced draws icons at its map clip's 0.7 (the `iconscale` command).
2. **Edge indicators:** new `MinimapEdges`, run on every `tick`.
   - The north art (Enhanced shape 179, exported `bl1mm_north`) sits on the window edge toward map north.
   - A diamond (`bl1mm_objective` at 0.55 × icon scale, with the objective's tint) sits on the edge for each objective icon outside the window, along the ray from the window centre. This replaces Enhanced's 360-frame sprites, which trace its own 220×180 frame.
3. **Mission givers:**
   - The Enhanced path uses Enhanced-only `NonStartedMissionData`, so v0.8 uses classic's own `IMissionDirector` script instead: `GetRedeemableMissions(pc)` > 0 gives `turnin`, otherwise `GetEligibleMissions(pc)` > 0 gives `newmission`, for each `WillowGlobals.ClientInteractiveObjects` entry with `MissionDirectives`.
   - Giver states are part of the rebuild key; option "Show mission givers".
   - The landmark sprite 1066 gains frames 11 `turnin` and 12 `newmission`, using Enhanced shapes 108/110 copied as 1301/1303 (vector only, checked).
4. **Build:** `swfbuild.py` takes the Enhanced HUD movie as a fourth input (see PROGRESS build commands). New `tools/upkprops.py` (class defaults) and `tools/swftimeline.py`.

**Tests:**
- **AS:** new frames and exports; icon scale on icons, player and dots; objective list; edge geometry (north top / east at 90° rotation, inside objective hidden, outside on the border with its tint); clear removes edges.
- **Mod:** Enhanced zoom; icon scale; givers (eligible "!", redeemable turn-in, accept rebuilds in place, failing call skipped, option toggle).
- Both pass. **Installed:** package `bf7c7ff4…4f66`, mod `23ca7e26…a5bf`; v0.7.0 is in `dist\v070\`.

**Not verified in game:**
- that pyunrealsdk calls `GetEligibleMissions(pc)` with the out array omitted (warns once and skips givers if not);
- the visual size and position of the edge icons;
- whether 403% matches the footage by eye.

**Run 11 (v0.8.0): crash at startup, cause outside the mod.** "Instruction at 0x01600C13 referenced memory at 0x00000000, could not be written."
- **Where:** `0x1600C13` is inside the engine's LZO decompressor (literal-run copies with an output-space check), writing to a NULL output buffer.
- **Why:**
  - Drive C: had **0 bytes free**, so the page file couldn't grow and a large allocation returned NULL.
  - `unrealsdk.log` and `Launch.log` stayed at 0 bytes, and no dump was written, for the same reason. PowerShell also reported "not enough space on the disk".
- **The v0.8 package checked clean:** 134 bulk-data records (67 compressed), identical to the original and to v0.7, with every compressed payload starting with the chunk tag `0x9E2A83C1` (scratchpad `bulkcheck.py`).
- **Cleanup:** the two Ghidra REA servers left running from the decomp were shut down, freeing their Java heaps and about 137 MB of temporary projects. C: then had 788 MB free. Deleting the Ghidra/JDK download zips (`Tools\_downloads`, already extracted; hashes in PROGRESS) brought it to about 1.5 GB.
- **Retest** once there is real headroom (several GB).

## 3n. Run 12 (v0.8.0) → v0.8.1

**Run 12:** T-Bone Junction and Arid.
- **Working:** zoom and icon size look right; `dock_mode: matrix`, so the HUD tilt took effect; the north marker shows.
- **Problems:**
  1. **"Double" waypoint at the window border.** When an objective sat just inside the window edge, its own (partly clipped) icon and the edge diamond both showed. The diamond appeared once the icon's centre crossed the inset border, but the icon stayed visible until the mask clipped it.
     - **Fix (movie, `MinimapEdges`):** a handoff. While the edge diamond shows, the objective's own icon is hidden; inside the inset window the icon shows and the diamond hides. At the switch point both sit at the same spot.
  2. **No mission-giver icons.** The log shows `mission giver check failed (TypeError: GetRedeemableMissions() missing 1 required positional argument: 'RedeemableMissions')`: pyunrealsdk requires out parameters as positional arguments.
     - F7 showed `givers: 5`, `giver_icons: []`.
     - The green "!" boxes in the screenshots are the game's own bounty-board icons.
     - **Fix:** call `Get*Missions(pc, [])`.

**Tests:**
- **Run-12 reproductions first:**
  - the fake giver now has pyunrealsdk's signature (the out argument is required) and failed exactly as in game before the fix;
  - the AS edge test asserts the handoff (the off-window objective's icon is hidden while its diamond shows, and restored when it comes back inside) and failed before the fix.
- Both suites pass.

**Installed:** package `e41bc83b…875c`, mod `da990b62…02a2`. v0.8.0 is in `dist\v080\`; bulk-data check clean.

**Not verified in game:** "!" and turn-in icons at givers.

**Not verified in game (v0.7.0, carried over):**
- that `transform.matrix` takes (F7 `dock_mode`);
- that the chosen window size looks right next to the HUD (Docked size option);
- the column positions with real ECHO calls and long mission titles.

## 3o. Repository setup (2026-10-24)

The user requested a review of AGENTS.md and the initial commit. Git was already initialized with no commits and the user's identity configured. Updated AGENTS with explicit test-first behavior changes (red → green → refactor), behavior-based test guidance, Conventional Commits, staged-file review and post-commit identity/message checks. Preserved the ban on agent co-author attribution. Added .gitignore for dist, extracted game packages/movies, Python caches, local environments and credentials.

This is a source/documentation baseline; no runtime behavior or installed files changed. No version bump or installation is required. Validation: both `python -I tools/test_minimap_as.py dist/phase2/HUD_minimap.gfx` (13 functions, attach and fallback paths) and `python -I tools/test_minimap_mod.py dist/phase2/HUD_minimap.gfx` passed. Installed hashes remain those in §3n; the v0.8.1 in-game checks are still pending.

## 3p. On-demand SDK mod releases (2026-10-24)

Renamed the local branch from master to main at the user's request. Added `.github/workflows/release.yml`, triggered only by workflow_dispatch. It validates matching mod versions and Python syntax, rejects existing tags, runs the existing SDK mod packager, verifies the archive against the source, and creates a GitHub release at the selected commit with only classic_minimap.sdkmod attached. Release notes explain the separately required local HUD build. Publication uses the built-in GitHub token with contents:write; concurrent releases are serialized. No remote is configured, so hosted execution is pending.

No runtime behavior, version or installed files changed; installed hashes remain those in §3n and its in-game checks remain pending. The game-dependent offline suites run locally because hosted runners have no game assets. Validation: built the SDK mod into dist/release-check, executed the workflow's embedded Python version/syntax and archive checks locally, and ran both minimap suites successfully. The archive verifier uses the packager's cache exclusions. Git whitespace checks pass. GitHub release creation and runner execution remain unverified until the workflow is pushed and dispatched; no release was published locally.

## 3q. Source-only CI (2026-10-24)

Added CI for main pushes/merges, PRs, merge queues and manual runs (PLAN_CI). Independent empty movie inputs and five native-contract stubs exercise the real builder and both existing suites without game assets or skipped assertions. Added SDK archive tests and failure-case tests for quality gates. Ruff F/E9 findings were limited to unused imports/variables; removed those and closed movie input reads in the tests. No mod runtime behavior, version or installed files changed; installed hashes and pending in-game checks remain those in §3n.

Added per-file line/branch thresholds, full Cosmic Ray mutation checks for the mod/packager in isolated source copies, actionlint, Python syntax/version checks, tracked-binary and unsafe Invoke rejection, threshold checks for new mod files, and pinned CI dependencies. Reports uploaded by CI are limited to named JSON/XML quality files. Validation: asset-free suites and gate tests pass, Ruff passes, actionlint 1.7.12 checksum verified and both workflows pass, coverage exceeds all configured floors, and both original suites pass against dist/phase2/HUD_minimap.gfx. Mutation baseline: mod 2,059/2,767 killed (74.41%; floor 70%), packager 32/39 (82.05%; floor 80%), no mutant timeouts/errors. Surviving mutants remain counted. Windows worker shutdown exposed a current-directory cleanup issue after results were recorded; changed the finalizer to leave the temporary directory first, verified source-copy/cleanup in a separate process, and removed the four empty directories from the baseline run. Hosted runner/merge protection configuration remains pending; no remote, commit, push or release was created by this change.

## 3r. Worktree-first development and main commit (2026-10-24)

At the user's request, AGENTS now starts new coding tasks in a new worktree on a task branch, preserves other tasks' checkouts, reuses the task's own worktree for continuations, and accounts for ignored local game/build inputs. Explicit instructions to work directly on main override the default; the user requested that exception for this commit. Added ignore rules for local worktree and assistant-state directories, leaving the existing enhanced-minimap-box worktree untouched. A subsequent user correction extends the no-attribution rule to branch names and worktree paths; AGENTS uses descriptive task prefixes such as feat/, fix/ and test/.

The commit includes the pending release workflow, CI and quality-gate setup from §3p–3q. The user has since configured origin as https://github.com/dacharl/bl1-classic-minimap.git. No runtime or installed files changed; installed hashes and pending in-game checks remain those in §3n. Validation remains the passing suites, lint/workflow checks, coverage floors and 2,806-mutant baseline recorded in §3q; staged content/whitespace and commit identity/message are checked before pushing. Hosted CI verification follows the push.

## 3s. Automatic parallel test workers (2026-10-24)

The user requested automatic worker counts for unit and mutation tests. Worked in `.worktrees/auto-parallel-tests` on `test/auto-parallel-workers` from main; renamed the task branch at the user's request to remove agent attribution, preserving all uncommitted work. Previously the unit checks ran serially and mutation CI forced four workers (also the local automatic cap). Added a shared available-CPU selector, default `--workers auto`, numeric overrides, a unit runner with independent Python processes and merged branch coverage, and independent movie/mod test cases. Mutation workers still run the original source suite serially inside isolated copies, avoiding nested pools. Updated CI and local commands; floors and mutant scope are unchanged.

Test-first scenarios failed before implementation for automatic selection, parallel case execution, mutation CLI selection and the Python 3.13 worker cleanup traceback. Cleanup now has one multiprocessing finalizer, which leaves the temporary directory before removing it. Additional regressions check CPU fallback/override and propagation of a failing child test. Validation: 11 unit cases pass with eight automatic workers on Python 3.13; combined coverage matches the recorded per-file baseline and clears every floor. Both original real-movie suites pass using the primary checkout's explicitly identified `dist/phase2/HUD_minimap.gfx`. Lint, repository and actionlint checks pass. Full automatic-worker mutation results are recorded below when complete.

Full mutation validation on Windows/Python 3.13.17 used eight automatically selected workers: mod 2,059/2,767 killed (74.41%; floor 70%), packager 32/39 (82.05%; floor 80%). All 2,806 mutants completed with zero timeouts, worker errors or cleanup tracebacks; scores match the earlier Python 3.11 baseline. The 11 unit cases also pass on Python 3.11 with an explicit two-worker override; a one-worker quality-gate subset verifies serial execution.

No game runtime code, version, installed file or hash changed. Installed hashes and pending v0.8.1 in-game checks remain those in §3n. Hosted CI remains unverified. The user subsequently requested committing the task branch and merging it into local main; no push or installation was requested.

## 4. In-game test

1. Launch, open **MODS**, enable **Classic Minimap**, and disable **Minimap Probe**.
2. Load a character in Fyrestone. **Expect:** the Fyrestone map art in a window at the top-right with your arrow in the middle, and landmark icons (Catch-A-Ride, New-U, transitions) where the full map shows them.
3. Walk and turn: the map scrolls and the arrow turns. Walk towards the edge of the map art: the arrow should stay centred.
4. Find enemies (for example skags outside town): red squares where they are.
5. Try **Rotate with player**. If the arrow doesn't point up, change the hidden *Rotation offset*, or tell me which way it points.
6. Fast-travel or change zone: the map switches. Also try a DLC zone if you have one.
7. Open and close the status-menu map: neither map should break.

**If something's wrong,** check `Binaries\Plugins\unrealsdk.log` for `[Classic Minimap]` lines.

**Unverified pieces, most likely to need a fix:**
- `unrealsdk.make_struct("ASValue", …)` resolving the `GFxMovie.ASValue` struct by short name;
- `PlayerTick` reaching the hook;
- Scaleform `attachMovie` / `getInstanceAtDepth` / drawing API;
- whether calling the native `UpdateObjects` 20 times a second is cheap enough;
- how the clip layer behaves when the map rotates.

## 3t. v0.9.0: Enhanced's minimap box and window (PLAN_V09.md)

**Request:** the Enhanced footage shows a framed box and a taller view. Research how Enhanced draws the box and decides the zoom.

**Findings:**
- **Box:** Enhanced's minimap clip (E sprite 187) is box art (shape 81, 263.4 × 238.5, vector) at depth 3, the window as a clip layer `mask` (sprite 83 → shape 82, **207.95 × 173.65** centred) at depth 4, and `maps` at depth 6. Edge indicators ride ±110 × ±92 on the box border.
- **Zoom:** a fixed **108%**, set only by script (`extInitComplete`: `Scales[3]` = 100, then `AnalogScale(+1 × 8)`).
  - The Minimap's `ApplyScale`/`ApplyAnalogScale` overrides only re-read `ClipSize`.
  - The root and Minimap `SetMapScale` pass the value through to `themap._xscale`.
  - The decoded Enhanced exe has no `SetMapScale` string.
  - The art and its placements are identical in both editions.
- **So:** v0.8's zoom already matched. The view differed because v0.8 squeezed classic's status-menu mask (820.75 × 527) to 220 units wide (**220 × 141** visible, about 20% less height than Enhanced), and there was no box art.

**v0.9.0:**
- **Movie:** `bl1mm_map` is built like E 187.
  - Enhanced shapes 81 (box) and 82 (window) are copied as 1307/1308. The window is wrapped in sprite 1309 and placed top-left anchored (−103.95, −86.8) at depth 4 with clip depth 6, so `map.mask` still reports the window rectangle.
  - Classic's `maps` (1132) sits at depth 6; the status-menu mask (1040) is dropped from the copy.
  - Edge indicators now sit on Enhanced's path (window half-size + 6 / + 5.15, i.e. ±110 × ±92) instead of inset.
- **Mod:**
  - Window constants are Enhanced's.
  - **Docked:** Enhanced's `p1` matrix as is (scaled only by Docked size).
  - **Zoom:** 108% × option. **Icons:** 100% × option (no 3.73× compensation).
  - **Custom:** keeps its meaning (window = 820.75 px × Size%, top-right at the margins).

**Tests:**
- **AS:** built-movie structure (box at depth 3, clip-layer `mask` at depth 4 masking to 6, `maps` at depth 6); edge positions on ±110 × ±92; handoff unchanged.
- **Mod:** dock matrix is Enhanced's own; zoom 108; icons 100; Custom geometry; no-transform fallback at 0.698.
- Both pass.

**Installed:** package `dc1292c5…ab9d`, mod `6df0c878…d7d7`. v0.8.1 is backed up in the worktree's `dist\v081\`; bulk-data check clean.

**Built on branch `worktree-enhanced-minimap-box`.**

**Not verified in game:**
- the box looks like the footage;
- the view height;
- edge indicators sitting on the border;
- "!" and turn-in givers (from v0.8.1).

## 3u. Run 13 (v0.9.0) → PLAN_V10

**Seen** (Enhanced footage vs classic at the Skag Gully sign):
- The box and window are the same size on screen as in the footage.
- The map is about 2.5–3× less zoomed than Enhanced.
- The objective edge diamond overlaps **N** when the objective is due north.
- An objective just inside the top of the window is mostly clipped.

**Causes** (PLAN_V10 research):
- **Zoom:** Enhanced's `extInitComplete` calls the native `QuickAccessInit` (`0x14139a970`, found through the native table and the minimap vtable) between `ApplyScale(100)` and `AnalogScale(+8)`.
  - It fits the player plus `GRI.ActiveWaypointData` into half the window, clamped to 100–400%. 108% is only the no-objective case.
  - Both editions use the same art, and classic runs at 108% as designed (F7 `themap_w` 841.85).
- **N overlap:** Enhanced does the same: its objective indicator draws over north, with no avoidance.
- **Sliver:** Enhanced also clips icons between the window edge (±86.8 in y) and its edge threshold (90); classic hands over at 92.

**No code changed yet.** The v0.10 plan: Enhanced's fit zoom computed in Python, and the objective handed to the edge diamond unless the whole icon is inside the window.

## 3v. v0.10.0: objective-fit zoom and full-icon edge handoff (2026-10-24)

Rebased `worktree-enhanced-minimap-box` onto main (`722be70`), preserving the uncommitted PLAN_V10 handoff with a stash, then restoring it. Read the merged AGENTS.md in full. Main's CI/release entries already used §3p–3r, so the branch's box/run-13 entries are now §3t/3u. The stash remains as a recovery copy.

**Changes:** Python reproduces the recorded `QuickAccessInit` corner projection, half-window fit, 100–400 clamp and +8 step. Collection snapshots the pawn and nonzero waypoint slots, with the native's RadarMgr gate. Capture normalizes the current art scale to 100%, retains the fit across objective refreshes, and refits for new anchors/HUDs and explicit rebuilds (F8, Rebuild now, status-menu close). The existing zoom option multiplies the captured fit. F7 includes `zoom_fit` with points, raw, fitted and final values. The movie shows the objective icon only when its whole extent fits the window; otherwise it shows the edge diamond on the existing box-border path. North overlap remains as in Enhanced. Both version fields are 0.10.0.

**Test-first evidence:** the nearby-objective hook scenario failed at 108 vs 400 before the zoom implementation. The F8 lifecycle test failed at 185.268496 vs 400 before explicit refitting. The diagnostics test failed because `zoom_fit` was absent. The movie's run-13 scenario failed because the icon at y=-80 stayed visible; the new handoff passes. Other scenarios cover the recorded 108/400/185.27/108 examples, zero slots, missing pawn/radar, the 150% option, objective-refresh preservation, anchor changes and horizontal/vertical edge cases at 100/150% icon size.

**Validation:** both suites pass against the real built movie, including attach/fallback paths. The asset-free CI suite, Ruff, repository checks and quality-check tests pass; per-file coverage floors pass (mod: 89.94% lines, 82.84% branches). All 2,895 mutation cases completed: mod 2,164/2,856 killed (75.77%, floor 70%); packager 32/39 killed (82.05%, floor 80%); no timeouts, worker errors or pending cases. Rebase integration fixes restore the AS suite's required `struct` import and add Enhanced's box/window shape IDs to the synthetic fixture. The movie extracted from the new package matches the tested movie by SHA-256. Installed v0.9 hashes were independently checked and are unchanged.

**Built locally (not installed):**
- `dist/phase2/GfxHUD_Minimap.upk` (fresh GUID): `5bae8e3fadf52711a8b26265b7572b8df8da6a882e89163b4bf740767dfebc29`.
- `dist/classic_minimap.sdkmod`: `63a57f97d0b5e067dd427c1e3364fd7f944183149d7496258e1dac7817cd6db6`.

Installed files remain v0.9.0 (package `dc1292c5…ab9d`, mod `6df0c878…d7d7`). No installation or new commit was requested. In-game fit parity, icon handoff during rotation, and respawn lifecycle remain unverified. The existing run-13 SDK log was read; it records v0.9.0 at 108% and turn-in giver icons.

## 3w. F7 console confirmation (2026-10-24, unreleased v0.10.0)

**Request:** give in-game console feedback when F7 is pressed. Classic's extracted Engine package confirms `LocalPlayer.ViewportClient`, `GameViewportClient.ViewportConsole`, and `Console.OutputText(Text)` with one string parameter. Its script calls OutputTextLine, which appends to console Scrollback and refreshes ConsoleBufferText.

**Change:** after writing the existing full diagnostic snapshot, F7 sends `[Classic Minimap] Diagnostic snapshot written to Binaries/Plugins/unrealsdk.log.` through the local player's viewport console. A missing player skips feedback; an unavailable console warns once in the SDK log and leaves the snapshot intact. Nothing opens the console automatically. This remains part of the uninstalled v0.10.0 build.

**Tests:** the F7 keybind test first failed because the console received no confirmation. It now checks the exact confirmation plus the full diagnostic log. Further cases verify snapshots survive an absent console (with one warning across repeated presses) and an absent local player. Both real-movie suites, asset-free CI, Ruff, repository checks and coverage gates pass. Mod coverage is 90.00% lines / 84.44% branches. All 2,898 mutations completed: mod 2,171/2,859 killed (75.94%, floor 70%); packager 32/39 (82.05%, floor 80%). No mutant errors, timeouts or pending cases; mutation gates pass. The runner exited 0 but Windows reported temporary-directory cleanup warnings after the test results were complete (FRICTION).

**Rebuilt SDK mod:** `f27f87fceb0458a580929ccf9ffb99845b4bc754ab1ac712584ba2bf2c8a110d` (supersedes §3v's SDK build). The movie package is unchanged. No installation: installed v0.9.0 hashes remain package `dc1292c5…ab9d`, mod `6df0c878…d7d7`. Console appearance is unverified in game.

## 3x. Rebase onto automatic parallel workers (2026-10-24)

At the user's request, rebased `worktree-enhanced-minimap-box` onto main `6f840a6` and restored the uncommitted v0.10/F7 changes from a new recovery stash. Resolved PROGRESS conflicts by retaining both the automatic-worker notes and the feature notes. Read the merged AGENTS.md in full. Main owns §3s, so branch entries now use §3t–3w and references were updated. All feature changes are unstaged; no new feature commit or installation.

Rebuilt the movie from the local inputs: its SHA-256 is unchanged (`b5bafe9e…50d1`). Both real-movie suites pass. The new automatic unit runner passes all 11 cases using eight workers; combined coverage meets all existing floors (mod 90.00% lines / 84.44% branches). Dependency consistency, Ruff, repository checks and actionlint for both workflows pass. All 2,898 mutations complete with eight automatic workers: mod 2,171/2,859 (75.94%, floor 70%), packager 32/39 (82.05%, floor 80%). Both mutation gates pass with no timeouts, worker errors, pending cases or cleanup tracebacks. Main's Python 3.13 shutdown fix resolves the warning recorded in §3w. Runtime source, feature tests and README match the saved pre-rebase versions exactly. The SDK build hash remains `f27f87fc…110d`; installed v0.9 hashes remain as in §3w. In-game validation remains pending.

## 3y. External performance telemetry plan (2026-10-24)

The user requested timing/performance telemetry as the next plan, then specified that timing must be removable from the artifact entirely and preferably external. PLAN_V11 now proposes a separately built optional profiler add-on, starting with a tested feasibility spike for reversible wrappers around the existing module-global calls. The standard core artifact must contain no telemetry imports, timers, counters, flags or dispatch; a profiling distribution reuses the identical core artifact alongside the add-on. It distinguishes an external add-on from an external OS profiler, synchronous call time from rendering cost, and measured spans from gaps. Separate instrumented builds are a fallback only after documenting external-measurement limitations.

The plan covers attach/detach/reload ownership, bounded inclusive aggregates, explicit report/reset buttons, deterministic hook/command and archive-isolation tests, coverage/mutation gates for the optional package, and attached/detached in-game overhead comparisons. F7 reuse is conditional on a verified SDK integration path. Planning only: no runtime/build changes, version bump, build, installation or new behavioral tests. Documentation passes `git diff --check`. Existing uncommitted v0.10 work and installed v0.9 files are unchanged.

The user also pointed to MCP diagnostic formatting in `C:/Users/Charles/Dev/steam-deck-scripts`. Read its BL1 producer, profile registration, reader/JSON validation, current MCP guide and evidence-summary specs. Added source references and a proposed independent performance-report envelope to PLAN_V11, plus a summary in PRIOR_RESEARCH. Plan explicit atomic JSON/text saves, bounded compact summaries, distinct identity/version registration, UTC versus monotonic semantics, immutable revisions and unknown live-state handling. Optional automatic checkpoints belong only to the profiler and must expose their measurement impact. Existing MCP readers are POC-specific; a new provider/adapter needs separate implementation and tests. No files in the earlier research repository were changed, and no MCP compatibility or live transport is claimed.

## 3z. Profiler add-on 0.1.0 and the frozen report contract (2026-10-24, PLAN_V11)

**What exists now:** `sdk_mods/classic_minimap_profiler/` (version 0.1.0, separate from the core, which is untouched at 0.10.0).
- `profiler.py` (no SDK imports): **Start** checks that `classic_minimap` is already loaded, is version 0.10.0 (decision 14) and has `mod.is_enabled`, then wraps 15 module-level functions plus `mod.on_disable`. The wrappers exist only while a capture runs.
  - `tick` is timed as a whole. `current_hud_movie` is wrapped only as the admission signal. `cmd` is timed by operation (nine named ops plus `other`). Twelve stage functions are timed by name.
  - Spans are inclusive, with a depth cap of 32. Values and exceptions pass through unchanged, and a failed call is counted as failed.
  - The capture stops itself from inside the `tick` wrapper once the chosen length (30/60/120/300 s) is reached, then detaches and saves. Nothing is written during the capture.
  - **Detach:** restores only the attributes still owned. Anything replaced by another mod becomes a detach conflict, with a restart/disable hint (ADR 0002).
  - **Abort reasons:** core disable → `core_disabled`; a replaced module or an in-place `importlib.reload` (detected by a new `mod` object) → `unsupported_lifecycle`; failed bookkeeping → `telemetry_error` (one warning, detach, the core keeps running).
  - **Saving:** temporary files, then archive rotation into `slot-1..8`, then atomic replace. A failed save keeps the previous report.
- `__init__.py`: MODS options **Capture length**, **Start performance capture**, **Dump performance report** (stop and save, plus one prefixed JSON record in the SDK log) and **Reset performance statistics**. Confirmations go to the in-game console; profiler disable stops a running capture.
- **Contract (H0 of the handoff):** [PERF_REPORT_V1.md](../research/PERF_REPORT_V1.md) plus `tools/fixtures/perf_reports/` (5 valid, 16 invalid). `tools/make_perf_fixtures.py` regenerates them from the real profiler; a test fails on any drift.
- **CI wiring:**
  - `run_tests.py` runs `test_profiler`; coverage includes the profiler.
  - The repository gate now checks version fields and floors for both mods (it also understands a re-exported `__version__`).
  - Mutation runs both suites in separate processes (`tools/test_mutants.py`; the per-mutant timeout is now 20 s, up from 10 s, because two suites run).
  - `run_mutations.py --modules` measures a subset locally.
  - The release workflow is unchanged: it packages only `classic_minimap`.

**Test-first evidence:** `tools/test_profiler.py` was written before the profiler and failed because the module did not exist. The injectable capture ID and the in-place reload case each failed first too. 35 cases, all passing:
- **Aggregation:** the plan's literal example (0.1/0.2/0.4 ms gives count 3, total 0.7, mean 0.233333, max 0.4, p95 ≤ 0.5), empty metrics as null, bucket bounds and overflow.
- **Lifecycle:** refusals, wrappers only while capturing, pass-through, admission, inclusive 2.0 vs 0.5 ms, conflict, disable, replaced module, in-place reload, reset, idle stop, depth cap.
- **Capture and report:** the timed stop saves once, contract shape and bounds, rotation keeps eight, a failed save keeps the last good file, dump, telemetry failure.
- **Glue, isolation and fixtures:**
  - glue buttons and console lines;
  - the core source has no telemetry words;
  - the standard and profiling distributions contain byte-identical core archives;
  - fixture sync and coverage of the handoff.
- **Integration:** the whole real core scenario (`test_minimap_mod.main`, on the synthetic movie) passes with a capture attached throughout. It observed 241 admitted ticks plus starts, collections, captures, rebuilds and commands, and the original functions were restored afterwards. `test_minimap_mod.main` gained an `on_import` hook for this; the core itself is unchanged.

**Validation:**
- Ruff and the repository gate pass.
- 49 unit cases pass in the automatic runner.
- Coverage: core 90.00%/84.44% (unchanged), profiler `__init__.py` 96.77%/100%, `profiler.py` 97.04%/91.67%.
- Both suites still pass against the real built movie.
- Mutation results: see the end of this section.

**Overhead benchmark** (`tools/bench_profiler.py`, local, this PC, game stubs; decision 8):
- **Collector memory:** 13.1 KB, **met** (limit 64 KiB).
- **Wrapper cost:** 1.55 µs per wrapped call. The scenario averages 12.8 wrapped calls per admitted update, so about **0.020 ms** per admitted update. The paired per-call median increment is 0.011 ms.
- **The p95 requirement is unresolved.** The harness's own noise is far wider than the 0.05 ms limit: paired increments run from p05 −0.69 ms to p95 +0.78 ms, and the unpaired p95 difference was 0.15 ms. That noise comes from the Python AS interpreter in the stubs. The benchmark therefore reports `unresolved` (exit 2) rather than passing or failing.
- A first run showed a large false overhead because `tracemalloc` was active during timing. Memory is now measured in separate runs.

**CI scope change (user request, same day):** mutation testing runs on demand only. The `mutation` job left `ci.yml`, which now runs just the two blocking checks: lint (Ruff, pip check, repository checks, actionlint) and unit tests with coverage floors. The job moved to `.github/workflows/mutation.yml` (`workflow_dispatch` only, 180-minute timeout, the same steps and artifacts). CI.md, README and AGENTS describe the split. The local full run started before this change was allowed to finish.

**Mutation hang (same evening):** that run stalled at 1,200 of 3,866 for an hour with all eight workers stuck.
- **Cause:** each worker was waiting on a `test_profiler.py` process spinning in a mutant's infinite loop. On Windows Cosmic Ray's timeout falls back from `killpg` to killing its direct child, the venv `python.exe` launcher. That ended `test_mutants.py` (job object) but not the suite, which kept the output pipe open.
- **Action:** stopped the run and its processes, and removed 16 orphaned `minimap-mutations-*` temporary copies.
- **Fix:** `tools/watchdog_run.py` runs each suite with an in-process deadline (`os._exit`), and `test_mutants.py` kills each suite's process tree at a 25 s budget, past Cosmic Ray's 20 s timeout, so such mutants are still recorded as timeouts.
- **Tests (written first):**
  - a looping grandchild is killed;
  - a hanging suite ends itself under the watchdog, and exit codes pass through;
  - the budget outlasts the Cosmic Ray timeout.
- **End-to-end check:** Cosmic Ray's own `run_tests` with a hanging suite now returns `timeout` after 9.1 s, leaving no processes behind.
- The full run was restarted.

**Installed (user request, game closed):**
- **Backup:** v0.9.0 first copied to the worktree's `dist\v090\` (mod `6df0c878…d7d7`, package `dc1292c5…ab9d`).
- **Installed, each verified by SHA-256 against its build:**
  - `classic_minimap.sdkmod` v0.10.0 `469b45db01ace82d1d6e4be8f0cc74c2e5d8415841a09a6a0df4c60521755ff7`. This is the same source as the `f27f87fc…` build in §3w; only zip timestamps differ, and the entries match the source byte for byte.
  - `GfxHUD_Minimap.upk` `5bae8e3fadf52711a8b26265b7572b8df8da6a882e89163b4bf740767dfebc29`.
  - `classic_minimap_profiler.sdkmod` 0.1.0 `c0fbbd4e3e5766b5ade8a24120a60a7bfb7c39e059db7970b047d9d8bc35d618`.
- The stock `GfxHUD.upk` is unchanged (`5c515c3e…3ea88`).

**Not verified:** the add-on has not been loaded by the real SDK (relative imports inside an `.sdkmod` package, button behaviour, console text). Captures in game, PresentMon/MangoHud comparisons and the H2 joint check are pending. `steam-deck-scripts` is unchanged. *(Superseded by §3aa: the real SDK loaded it and a capture completed.)*

## 3aa. Run 14 (v0.10.0 + profiler 0.1.0): objective "wobble" at the window edge; first in-game capture

**Seen** (two screenshots, Arid near Bone Head's camp, standing still):
- An objective near the top-left of the window kept switching between the edge diamond and its in-map icon.
- The classic compass's objective diamond blinked green/white at the same moments.

**Log** (`unrealsdk.log`):
- No rebuilds after 00:50:03, so the switching was not the mod re-collecting markers.
- **F7** (three snapshots): `tint` None; zoom fit raw 286.18 → fitted and final **294.18%** from 2 points (pawn plus one waypoint about 7,140 UU away); `themap_w` 2,293; 28 markers.

**Cause:**
- The classic objective art is animated. Sprite 1050 holds the diamond (shape 1047, 45.1 units) and a ring (shape 1049, 40.2 units) that scales 1.0 → 2.2 over 12 frames and loops (`tools/swftimeline.py … 1050`). The blink is the same art, which is why the compass blinks too.
- v0.10's handoff measured the icon's live `_width`, which swings between about 24.8 and 48 units with the pulse. Near the edge the "whole icon fits" test therefore flipped with the animation.

**Fix (movie only):** `MinimapEdges` takes the icon's half-size from its scale, not its live width: `OBJECTIVE_HALF` = 45.1 × 0.55 / 2 = 12.4 units × `o._xscale` / 100 × the `maps` scale. The mod is unchanged at 0.10.0 (so the profiler's version allowlist still applies).

**Test-first evidence:** a new AS scenario pulses the icon's width (24.8 → 48 → 30 → 48 → 24.8) at y = −70, where the static icon fits. It failed at 48 before the fix and passes now; the earlier run-13 cases still hold.
- Both real-movie suites pass, and the 52 unit cases plus Ruff pass.
- **Rebuilt package:** `GfxHUD_Minimap.upk` `5eefdf81368d775a3ebd8e9046d1d9666f65c70210998a1fafbd5976fdb76d03` (fresh GUID). The movie extracted from it matches the tested `HUD_minimap.gfx` `fcd05c20…5fc3`.
- **Installed** (user request, game closed): the previous package `5bae8e3f…bc29` was backed up to the worktree's `dist\v0100\`; the installed copy's SHA-256 matches the build (`5eefdf81…6d03`). The mod and profiler are unchanged.

**Profiler in game, first real evidence:**
- The SDK loaded the add-on (so relative imports inside the `.sdkmod` work), and Start produced a completed 60 s capture saved to the reports folder.
- **Summary:**
  - 872 admitted updates out of 2,524 ticks;
  - admitted mean 2.19 ms, p95 ≤ 5 ms, slowest tick 25.6 ms;
  - `objective_key` 2.31 ms mean (100 calls; includes `giver_states` 0.87 ms and 9 `script_count` calls each);
  - `hidden_reason` 0.47 ms per admitted tick (max 9.9 ms);
  - `cmd.tick` 0.32 ms (max 11.1 ms);
  - `threat_string` 0.58 ms (187 calls).
- These are synchronous elapsed times on the game thread, not frame cost. No frame-time comparison yet. Optimisation candidates for a later plan: `objective_key`/givers and `hidden_reason`.

## 3ab. HUD gradient textures shifted: bright damage indicator, green/red/white box (2026-10-24)

**Seen:**
- The damage-direction indicator was a bright, opaque yellow wedge instead of a faint one.
- The minimap box showed green, red and white behind it. Enhanced's box is a faint light blue.

**Cause (from the movies' tags, `scratchpad/gradscan.py`, `gradmap.py`):**
- GFx keys its external gradient images (`DefineExternalGradient`, tag 1003, e.g. `HUD_G4.tga`) by a gradient's position among all gradient fills in file order. Classic's HUD has exactly 14 gradient fills and 14 records, ids 0–13.
- The builder inserts its block before the first `ShowFrame`, after 4 of classic's gradients. That block brings 12 gradient fills of its own: Enhanced's box (shape 1307: 4 fills of light blue (6, 182, 249) fading from alpha 127 to 0) and the status-menu map art (shapes 1083, 1093, 1129).
- **The box** therefore took classic's ids 4–7, the textures of classic shapes 82 (white), 93 (red), 239 (dark red) and 251 (green): the green/red/white.
- **Classic's later shapes** moved to ids 16–25, which have no record, so they rendered as raw vector gradients. The damage indicator (shape 707, an opaque yellow vector gradient) lost texture 13: the opaque wedge.
- **History:** the status-menu art has been inserted since the first package, so the indicator has probably been off since then; the box made it visible.

**Fix (builder only):**
- `swfbuild.shift_gradient_images` counts classic's gradient fills before the insertion point (4) and the inserted ones (12), then adds 12 to every classic 1003 id ≥ 4.
- Classic shapes keep their own textures. The inserted fills have no record and render as their own vector gradients: the box's faint blue, as in Enhanced.
- `swfdeps.shape_gradient_count` counts gradient fills, including line fills and inline style changes.

**Test-first:**
- `test_ci.SourceChecks.test_classic_gradients_keep_their_external_images` builds a synthetic classic HUD: one gradient shape before the first `ShowFrame`, two after, three 1003 records, plus a two-gradient box. It expects each classic shape to keep its own image and the box to have none. It failed on the missing counter, then passes.
- **On the real build:** every classic shape maps to the same image as in stock classic, and the inserted shapes map to none. The previously installed movie fails the same check.
- Both real-movie suites, 53 unit cases and Ruff pass.

**Package:** `GfxHUD_Minimap.upk` `e2b687c1936942198b4da8404557a28b7b132fd552776b4719cfcbbd2886ab51` (fresh GUID; it also contains §3aa's handoff fix). The embedded movie matches the tested `HUD_minimap.gfx` `a3e95200…3c55`. **Installed** (user request, game closed): the previous `5eefdf81…6d03` was backed up to the worktree's `dist\v0100-wobblefix\`, and the installed copy's SHA-256 matches the build. The mod is unchanged.

**Unverified:** that Scaleform draws the box's raw vector gradient with its alpha (expected faint blue), and that the damage indicator looks as it did before the minimap.

**In game (run 15):** the box is faint blue, with no green/red/white; the damage indicator has not been checked yet.

## 3ac. Run 15: Tartarus Station showed T-Bone's map → v0.10.1, profiler 0.1.1 (2026-10-24)

**Seen:** after travelling from T-Bone Junction (DLC3) to Tartarus Station (DLC4), the minimap art did not match the full map.

**Log:**
- The trip kept the same HUD (no "map attached"), so the mod rebuilt in place. Both zones use frame `dlcmap1` (31).
- F7 and the anchor log show the Tartarus anchor (`DLCMap dlc4_maps.dlcmap_dlc4tartarus`), but art of 249.6 × 500.3 at 100%. That is exactly `dlc3_maps.dlcmap_HUB`'s size, giving CoordScale (2.0045, 1).

**Cause:** frame `dlcmap1` (status-menu sprite 1132 frame 30) loads the DLC movie with a frame action, `getURL(_root.LoadDLCPackage, "themap")`, which runs only when the playhead enters the frame. Already on `dlcmap1`, `InitMapFrame`'s `gotoAndStop` was a no-op, so DLC3's movie stayed.

**Fix (mod 0.10.1):** `collect()` sends `frame~none` before `InitMapFrame` when the anchor's DLC package differs from the previous one. The loader then runs again; the empty placeholder (1131) has zero width, so the capture waits in `framewait` until the new movie loads. A rebuild within the same DLC does not blank the map.

**Test-first:**
- The mod suite's helper fake now loads a DLC only on frame entry, as the real frame action does.
- A DLC3 → DLC4 in-place rebuild failed (DLC3 still loaded) before the fix and passes now. A same-DLC rebuild triggers no reload.
- A new guard test requires the core's version to be in the profiler's allowlist.

**Versions:**
- Mod 0.10.1 (both fields).
- Profiler 0.1.1: allowlist `("0.10.0", "0.10.1")`. Report fixtures regenerated; only `producer.version` changed.
- PowerShell's `Set-Content -Encoding utf8` added a BOM to both mod files during the bump; it was stripped before testing (FRICTION).

**Validation:** Ruff, the repository gate, 54 unit cases and both real-movie suites pass.

**Built, not installed:** `classic_minimap.sdkmod` 0.10.1 `0042d3c4bd00eee60b8182d31ce871b43fb8e1ce5c889f85049732380ea5873c`, `classic_minimap_profiler.sdkmod` 0.1.1 `0f642d3193525dcbe75959cff09bab258c58e6a96337b927ed5e1acf4aa1d5c8`. The package is unchanged (`e2b687c1…ab51`). The mutation run in progress tests the earlier sources.

## 3ad. Threat markers: Enhanced's diamond, counter-rotated (2026-10-24)

**Request:** threat markers looked large and square; the compass and objective waypoints use diamonds.

**Research (E_HUD movie data, `swftimeline.py`, scratchpad `shapedump.py`):**
- Enhanced's `maps.enemy` (sprite 128) holds shape 127: a red (255, 0, 0) diamond with vertices at ±5.8 units, inside a black diamond outline at ±7.2, 14.45 units across, solid fills only.
- Its `Minimap.UpdateThreats` duplicates the clip without scaling, and `CancelOutIconRotation` sets every threat's `_rotation` to −`currentRot`.
- **Ours:** since v0.6, `UpdateThreats` drew a red 10 × 10 square with the drawing API (classic's map art has no enemy clip), with no outline and no counter-rotation.

**Change (movie only; the mod is unchanged):**
- Shape 127 copied as 1310, with a one-frame wrapper 1311 exported as `bl1mm_enemy`. It has no gradients, so classic's gradient mapping (§3ab) is unaffected (re-checked: classic shapes keep their images).
- `UpdateThreats` attaches `bl1mm_enemy` into `maps` (Icon size still applies) and sets `_rotation` = −`maps._rotation`. `MinimapRecenter` updates every threat's rotation each tick as the map turns.
- `THREAT_COLOR`/`THREAT_HALF` removed. Both synthetic Enhanced movies (CI fixture, gradient test) gained a stub shape 127.

**Test-first:** the AS suite failed while dots were drawn squares. It now checks that threats are `bl1mm_enemy` art and not drawn, counter-rotated at placement and after a recentre changes the rotation (and back to 0 when north-up), and that the export points at a wrapper around 1310.

**Validation:**
- Both real-movie suites, 54 unit cases, Ruff and the repository gate pass.
- Coverage floors hold: core 90.16%/85.29%, `swfbuild.py` 97.20%/80.30%.
- **Package:** `GfxHUD_Minimap.upk` `4a840f56b85b61ea9d9bcf86a9fa6f992b2c05f8aae9f1804a4ed9d4d6efcabc`, embedding the tested movie `3b2095bc…a08d`.

**Installed (user request, game closed; previous files backed up to the worktree's `dist\v0100-run15\`, each installed copy's SHA-256 matching its build):**
- `classic_minimap.sdkmod` 0.10.1 `0042d3c4…873c` (§3ac);
- `classic_minimap_profiler.sdkmod` 0.1.1 `0f642d31…d5c8`;
- `GfxHUD_Minimap.upk` `4a840f56…cabc`.
- The stock `GfxHUD.upk` is unchanged.

**Unverified in game:** the diamonds' look and size next to Enhanced's, counter-rotation with "Rotate with player", the Tartarus fix, and the damage indicator.

## 3ae. Second mutation stall and the floors (2026-10-24)

**Seen:** the restarted full run stopped at 3,850 of 3,866. Six `watchdog_run.py` suites (profiler mutants) had been spinning for an hour past their deadlines, at about 5,000 s CPU each.

**Cause:**
- These mutants loop inside a single C call that holds the GIL (for example, a mutated integer power in the percentile rank), so the watchdog thread never ran.
- `test_mutants.py` itself had died with the venv launcher, as before, so nothing enforced the deadline.
- Separately, the suites ran in a new POSIX session, outside the process group Cosmic Ray kills, which would have allowed the same stall on Linux CI.

**Fix (`tools/test_mutants.py`):**
- **POSIX:** suites stay in the command's process group.
- **Windows:** suites run on the base interpreter (`sys._base_executable`) and are assigned to a kill-on-close job object, so they die with the command however it dies.
- The 25 s budget and the watchdog stay as extra layers.
- **Test (written first, failed, passes):** `test_runners.test_suites_die_with_a_killed_mutation_command` starts the command with a suite spinning in C code, kills it with Cosmic Ray's own `_kill_process_group`, and requires the output pipe to close and the suite to be gone. All 11 runner cases pass. The POSIX branch runs only in CI.

**Results of the stalled run (3,850/3,866; log kept in `dist/ci/mutations-full-stalled-3850.log`; it tested the sources before §3ab–3ad):**

| File | Killed | Score | Floor |
|---|---|---|---|
| core | 2,166 of 2,851 | 75.97% | 70% |
| packager | 33 of 39 | 84.6% | 80% |
| profiler `__init__.py` | 31 of 34 | 91.2% | **85%** (new) |
| profiler `profiler.py` | 759 of 926, 29 timeouts | 82.0% (80.6% if the 16 unfinished count as undetected) | **78%** (new) |

These floors are now in `pyproject.toml` and CI.md. A complete run with the fixed command is still pending; mutation runs are on demand only.

## 3af. Run 16: flat turn-in diamond, zoom off after a level change → v0.10.2, profiler 0.1.2 (2026-10-24)

**Seen:**
- DLC maps work after T-Bone ↔ Tartarus.
- The gold turn-in objective looked flat: a solid, tilted gold square instead of a diamond with a ring and a dark centre.
- Arid's zoom changed after getting into a vehicle (moderate on foot, very close afterwards).

**Turn-in diamond:**
- **Cause:** the tint used `Color.setRGB`, which paints every pixel one colour. The objective sprite (1050) has a faint 45-unit square glow (shape 1047), the diamond ring and a dark centre; all three became solid gold, so the glow showed as a big gold square. Enhanced's turn-in giver art (shape 108) is a green "?", unrelated.
- **Fix (movie):** new root `MinimapTint(clip, rgb)` applies a multiplying colour transform: ra/ga/ba = channel / 2.55, alpha and offsets untouched. White turns gold and the dark centre stays dark. It is used for the in-map icon and its edge diamond.
- **Tests:** the VM's `Color.setTransform` is recorded, and `tint_of()` rejects any `setRGB`. The suite failed while `setRGB` was used.

**Zoom after the vehicle:**
- **Evidence (F7):** at 02:16:06 the fit's player point was (−381, 537, −11146), Tartarus coordinates while the map was Arid. The capture ran after the trip, before the game moved the pawn: raw 61%, shown 108%.
- The status-menu-close rebuild at 02:16:12 refitted with the real position, about 280 UU from the objective, giving 400%, which is correct.
- **Fix (mod 0.10.2):** a capture that fits also sets `fit_pending`. The first time the map is shown afterwards (no loading movie, levels settled), `refit_when_shown` refreshes **only the pawn point**, keeping the capture's waypoints, since objective changes keep the fit as in Enhanced. It refits and redraws only if the points changed. It runs once.
- **Tests:** a capture during a loading movie with a stale, far pawn gives 108%; then the pawn is placed and loading ends, and the zoom must be 400%, staying there. This failed before the fix. The existing "objective change keeps the fit" scenario caught a first attempt that refreshed waypoints too.

**Versions:** mod 0.10.2; profiler 0.1.2 (allowlist adds 0.10.2); fixtures regenerated (producer version only). All version edits were made with the Edit tool (no BOM).

**Validation:**
- Both real-movie suites, 55 unit cases, Ruff, the repository gate and coverage pass (core 90.41%/84.53%, `swfbuild.py` 97.25%/80.30%).
- **Builds (not installed):**
  - `GfxHUD_Minimap.upk` `5eb071eb9244557f27edf434f0209c6b27b2d755f5f66d72d6ade36405e461f1` (movie `80148649…2ad5`);
  - `classic_minimap.sdkmod` 0.10.2 `e7d6da7151c29ddc592cb9be9f42bf5a2d8755d60f9f0fcd38c4b013fc00d42a`;
  - `classic_minimap_profiler.sdkmod` 0.1.2 `497fe5c53e251ad2fc5ac4f10b7637b0a7cd9e59b7fdd9fd6b6d6fc8547f174e`.

**Not changed:** closing the status menu still refits (PLAN_V10's choice). That is what corrected the zoom in run 16, and Enhanced itself refits only at HUD init.

**Installed on the Steam Deck too (run 17, below).**

**Installed (user request, game closed):** previous files (mod 0.10.1, profiler 0.1.1, package `4a840f56…cabc`) were backed up to the worktree's `dist\v0101-run16\`. The three builds above are installed, each installed copy's SHA-256 matches its build, and the stock `GfxHUD.upk` is unchanged.

## 3ag. Run 17: Steam Deck, and a conflict with Extended UI (2026-10-24)

**Seen:** v0.10.2 on the Steam Deck (Proton) showed no minimap and no error.

**Log (the Deck's `unrealsdk.log`, read by the agent):**
- The SDK and mod loaded. At 03:39:52 Classic Minimap redirected the HUD template to `GfxHUD_Minimap.FlashMovie.HUD`.
- By 03:41:00 the template and the live HUD used `GFxMovieInfo'GfxHUD_MOD.FlashMovie.HUD'` instead. F7 (five snapshots) showed phase `stockhud`, `root functions: False`, and both MovieInfos `GfxHUD_MOD`.
- **Cause:** another mod redirects the same `hud_instance` template to its own replacement HUD movie and loads later. The user confirmed it is **Extended Item Cards ("Extended UI" 1.3.2)**. Only one replacement HUD movie can win the template; our mod correctly idles on a HUD without its root functions, but its hint ("load a save or change area") was misleading here.

**With Extended UI disabled (second log, 03:53):**
- `map attached` → `map ready: Arid (frame 2), 24 markers` → `minimap shown` about 3 s later.
- The Deck's anchor record matches the Windows PC exactly (Arid Transform and CoordScale), so the maths is identical under Proton.

**Open:**
1. Compatibility with Extended UI. Building our package on top of its HUD movie, instead of the stock one, would let both work; that needs its package from the Deck.
2. Diagnostics should name a foreign HUD movie ("another mod replaced the HUD: GfxHUD_MOD") instead of the generic hint.

## 3ah. Release/install, version and diagnostic tools (2026-10-25)

**Request:** implement FRICTION's first three ranked tooling improvements. Work is on
`feat/release-diagnostics` in `.worktrees/release-diagnostics`; no game files were installed.
Research/design: PLAN_RELEASE_TOOLS. Commands and limitations: [TOOLS.md](../TOOLS.md).

**Cause of repeated work:** releases and installs were manual, diagnostic evidence needed throwaway
parsers, and core/profiler/fixture versions were edited independently. The profiler version actually
lives in `profiler.py` and is re-exported; the fixture generator had a hardcoded core version.

**Changes:**
- `bump_version.py` synchronizes core/profiler declarations, preserves the compatibility history,
  regenerates all 21 contract fixtures and updates the two contract introductions. Dry runs do not
  write; generator failures restore original bytes. No runtime version was bumped in this task.
- `release.py` takes explicit local input paths, builds the movie, runs both real-movie suites,
  repacks with `--new-guid`, builds the standard artifact and optional profiler, and publishes a
  completed local directory with a SHA-256 manifest. Existing release directories are refused.
- `install.py` verifies the manifest, archive versions, installed stock hash and all package bytes
  against reconstruction from stock (including bulk-data relocation). It checks the process twice,
  backs up selected installed files by replaced version and UTC date, stages/copies/verifies them,
  rolls back copy failures and prints PROGRESS rows. Profiler installation requires `--profiler`.
- `diag.py` reads local/copied logs, safely parses F7 dicts, decodes zoom inputs, flags foreign HUD
  names and summarizes warnings/events, anchors and the latest profiler text summary. Nonfinite GFx
  reads become null; malformed/truncated records are reported without losing prior valid evidence.

**Validation:** test-first CLI scenarios against temporary repositories, synthetic package/movie inputs,
logs and fake game folders; confirmed CLI boundaries with the user. All 80 default unit cases and
all existing per-file coverage gates pass, as do Ruff and the repository checks. Scenarios include
partial-build cleanup, repeatable version bumps, preservation of old producer versions, generator
rollback, game-running refusal, tampered payload/manifest refusal, dry runs, profiler opt-in, copy
rollback and non-execution of log text. Both real-movie suites also pass through `release.py` with
the primary checkout's extracted game inputs. `diag.py` reads the current installed SDK log/settings.
Mutation testing was not requested and was not run; floors and mutation scope are unchanged.

**Local validation release** (`dist/releases/validation-0102`, never installed):
- `GfxHUD_Minimap.upk`: `a090b80c9a9b3029d8b0825f349f7804643ceda11944c0378fdb8a13576b2b97`;
- `HUD_minimap.gfx`: `8014864975257b7486d3157fe008f75abe38f8aaf1252cd33f2acfa9bc5b2ad5`;
- `classic_minimap.sdkmod`: `7a1ab22f025f42ad7eb97abb3350dff3f172a34a0dbf15c150fdaf5bb178d390`;
- `classic_minimap_profiler.sdkmod`: `1cde794e68c6d1cfbf19a3f81525cc675e1140795bee97cebbc26d17824ea034`.

The package GUID is fresh per build, and ZIP timestamps can change archive hashes; these identify
this validation bundle only. The stock input hash is `5c515c3ea119bcffbaf774657d58b995b41a4f0daf6d9f3291ca9fb14b93ea88`.

**Installed hashes:** unchanged from §3af; no game files were copied. **Unverified:** a real install
through the new installer and subsequent in-game play. SSH deployment is deferred. Saved-log
foreign-HUD detection does not implement PLAN_V12's runtime console message or HUD merge.

## 3ai. PLAN_V12: runtime HUD merge → core v0.12.0, profiler 0.1.3 (2026-10-25, offline only)

**Built, not installed, not played.** Branch `feat/runtime-hud-merge`. Plan step 0 (the in-game spike that shows GFx
loads a `GFxMovieInfo` constructed from Python) has **not** been run: it needs the game.

What changed:
- `sdk_mods/classic_minimap/swfmerge.py` (decision 10): the tag walk, the shape/gradient counter (moved out of
  `swfdeps.py`, which re-exports it), the prefix/id/export/function-name/gradient checks and the splice. The mod and
  `swfbuild` both use it.
- **Manifest (decision 2, adjusted):** `upkpatch` can only replace an existing export, so a second movie in
  `GfxHUD_Minimap.upk` was not feasible. Instead `swfbuild` puts a Metadata tag (code 77, JSON) right before our block
  in our own movie, holding the mod version (decision 11), stock's prefix tag codes, the gradient counts and the
  block's character ids, export names and root function names. The runtime slices the block out of our movie by tag
  count, so it still never reads or diffs the stock HUD. Players skip tag 77.
- **Mod:** `redirect()` merges when the template holds a movie that is neither stock nor ours (`merge_into`).
  `Engine.WorldInfo:IsMenuLevel` POST runs `reconcile()` (returns at once when the template is ours or merged; a
  refused movie is not re-checked). The merged `GFxMovieInfo` is built with `construct_object(..., KEEP_ALIVE,
  template_obj=foreign)` and its `RawData` set. Disable restores their movie only while the template still holds the
  merged object; re-enable reuses the merge while their movie is unchanged. Status goes to the SDK log, a console
  line and the MODS description (`set_status`); a refusal keeps their template and leaves the minimap idle (ADR 0003).
- Versions bumped with `tools/bump_version.py 0.12.0 --profiler-version 0.1.3`.

Evidence: the real build's manifest (102 characters, 17 functions, 12 gradients, 4 before the block, 158 prefix tags,
105 block tags) matches the PLAN_V12 research. Merging our block into the stock classic HUD reproduces our own movie
minus the manifest tag exactly, and `test_minimap_as.py` passes on it. A merge takes about 0.5 s in CPython (once per
session, no cache, decision 6).

Tests (red first): `tools/test_swfmerge.py` (27 cases: synthetic foreign HUD, splice, gradient shift, every refusal,
shape-walker records) and new scenarios in `test_minimap_mod.py` (merge on the POST hook, reuse, restore rules,
refusals, status lines, version mismatch, stock path unchanged). `test_workflow.py` no longer hard-codes versions. Both
movie suites, all 107 unit tests, the coverage floors (swfmerge 98.9% line / 95.7% branch; floors 90/80) and Ruff
pass. Mutation testing was not run (a swfmerge floor of 70 is configured).

**Real Extended UI HUD (local-only check, same day):** `GfxHUD_MOD.upk` (SHA-256 `6a6e29d1…e489`, from the earlier
research session's scratchpad) → `upkpatch extract` → `swfmerge.merge` against our v0.12.0 movie: accepted, 840,389
bytes (the size PLAN_V12 measured), 1.6 s in CPython. `test_minimap_as.py` and `test_minimap_mod.py` both pass on
the merged movie (the mod suite skips its runtime-merge scenarios there, since a merged movie carries no manifest).
The merged file is kept under ignored `dist/` only.

**Spike built, not installed:** throwaway `dist/spike/classic_minimap_spike.sdkmod` (ignored by Git, never
committed; source in `dist/spike/classic_minimap_spike/`). F6 builds a `GFxMovieInfo` from GfxHUD_Minimap's own movie
with timings for every step, points the template at it and logs `SPIKE PASS` when the next HUD runs it (`mmfallback`
exists); F5 restores. Only checked against fakes.

**Spike run (PC, 2026-10-25 19:24, run 18): PASS.** First attempt (area change only) was inconclusive: the HUD
persists across travel, so no new HUD spawned. Second attempt: F6 in game, then quit to menu and load a save.
Every HUD that spawned afterwards (`WillowHUDGFxMovie_3` to `_6`) had `MovieInfo` = the constructed object and
`mmfallback._x = -20000`, i.e. GFx loaded our movie from a `GFxMovieInfo` built in Python. No crash. Timings for the
616,279-byte movie: `bytes(RawData)` 708 ms, `construct_object(template_obj=)` 0.2 ms, `RawData = list(bytes)` 164 ms,
read-back 708 ms (identical). `template_obj` copied the data properties (only name, hash, flags, net index and
archetype differ). The installed 0.10.2 core idled on that HUD as designed ("not GfxHUD_Minimap.FlashMovie.HUD"),
so no minimap was drawn; the check was the log line. Cost of a merge in game: about 0.7 s per movie read plus 0.2 s
write, around 1.6 s once per session; above decision 6's 1 s trigger for a disk cache, and the read of our own
movie is avoidable (a cheaper read, or caching the block bytes, is the first thing to try).

**v0.12.0 release bundle built (not installed):** `tools/release.py --output dist/releases/0.12.0 --profiler` (it runs
both movie suites on the built movie). SHA-256: `classic_minimap.sdkmod` `cfa93923…0d45`,
`classic_minimap_profiler.sdkmod` `988511a9…6376`, `GfxHUD_Minimap.upk` `a858eed8…d0f4`, `HUD_minimap.gfx`
`8b435820…38be`; stock input `5c515c3e…ea88`. The package GUID is fresh per build.

**v0.12.0 installed and played on the PC (run 19, 2026-10-25 19:46):** without Extended UI the minimap works as
before; with Extended UI enabled both the minimap and its cards, armor bars and compass work after quit to menu
and load (user report). From the log (Extended UI session): the merge ran once, `merged in 3.40s (840389 bytes)`
(the bytes match the offline merge), then "Merged into GFxMovieInfo'GfxHUD_MOD.FlashMovie.HUD''s HUD movie…" in
the log. That is about twice the 1.6 s the spike predicted: two 0.7 s reads, the pure-Python merge (1.6 s on a
fast desktop) and the 0.2 s write; it happens once, in the first `IsMenuLevel`, and is above decision 6's 1 s
trigger for a cache. **Level-change delay (user):** Arid Hills to Arid Badlands, the HUD was up several seconds
before the minimap. Log: hidden "loading movie" 19:47:42.2, map ready 19:47:49.8 (anchor wait 7.6 s), shown
19:47:52.5 (our 3 s settle rule). The earlier 0.10.2 session's Arid to Dry change took 4.1 s to ready plus the same
3 s, so a delay existed before the merge; the transitions differ, so whether Extended UI adds to it is not
established. Both are tuning-pass items (PROGRESS).

**Steam Deck run with Extended UI 1.3.2 (run 20, 2026-10-25 20:18, v0.12.0, user-supplied log): works.** Extended UI
loaded at 20:19:03; the first `IsMenuLevel` merged at 20:19:50 (`merged in 4.36s (840389 bytes)`, 3.40 s on the PC);
the next HUD attached the map at once, "Merged into … HUD movie" shows in the F7 snapshot (`hud_merge`,
`template.MovieInfo` = `GfxHUD_MOD.FlashMovie.MinimapMergedHUD`), Arid showed 24 markers and the 108% zoom, and a
trip to the DLC2 lobby (`dlcmap1`, frame 31) rebuilt in place in 3.6 s with the map shown 3.5 s later. No "Refused" or
error line from our mods (the `ERR` lines are other mods' invalid `.sdkmod` files). The merge is the one visible
hitch: 4.4 s on the Deck, once per session.

**Still unverified:** (the Deck run with Extended UI is done, see above) the Deck run, and (a constructed `GFxMovieInfo` honoured by GFx; `bytes(RawData)` / `RawData = list(...)`
speed and typing in pyunrealsdk; `template_obj` copying their texture references); the merge against the real
Extended UI HUD (its package was not at hand, so only the synthetic fixture and the stock HUD were tested); the Deck
run (plan step 4). If the spike fails, switch the install to the package fallback (decision 9).

## 3aj. PLAN_V13: the player-built movie, one-file install → core v0.13.0, profiler 0.1.4 (2026-10-25, offline only)

**Built and tested offline, not installed, not played.** Branch `feat/player-built-movie`.

What changed:
- **Builder in the mod (decision 16):** `swfbuild.py`, `as2asm.py`, `swfdeps.py` and `upk.py` moved into
  `sdk_mods/classic_minimap/` (relative imports inside the package, plain imports for the offline tools). The
  `tools/` files of those names are wrappers loading the mod's copies (`tools/mod_source.py`). `upk.Pkg` takes
  bytes, and `upk.movie()` extracts a package's movie; `upkpatch.py` keeps only the repack and imports the rest.
- **Original art (decisions 5, 12–15):** `swfbuild.build(hud, status_menu, enhanced=None, version=None)`. Without
  the Enhanced movie, it writes:
  - "X" (turn-in, gold `FFC420`), "!" (gold `FFCC00`) and "N" (white) as `DefineEditText` glyphs (ids 1312–1317),
    each over four black copies offset by 1 px, inside sprites 1301/1303/1305;
  - a copy of the HUD's own empty `WillowBody` font record (id 1318), because the HUD's font 119 is defined
    after the block's insertion point;
  - our own `DefineShape3` box, window and threat diamond at Enhanced's bounds (1307, 1308, 1310).

  Classic's objective diamond is unchanged.
- **`hudmovie.py` (the in-game build):**
  - finds the inputs: classic's `GfxHUD.upk` and `menus_ingame_redux.upk`, and Enhanced next to classic, through
    Steam's `libraryfolders.vdf` (Wine's `Z:` for POSIX paths), or the hidden `Enhanced folder` setting;
  - keeps the movie cache (`classic_minimap_hud.gfx` and `.json`) keyed on every input's SHA-256, the art choice
    and the version;
  - falls back to original art when Enhanced can't be used, and fails as `BuildFailed` when a classic input can't
    be used;
  - keeps the movie in memory when the cache can't be written;
  - checks the inputs against `KNOWN_INPUTS` (see PLAN_V13 "As implemented").
- **Mod:**
  - on enable it builds or reads the movie, constructs `MinimapHUD` (`KEEP_ALIVE`, `template_obj` = the stock
    movie) and points the template at it, with no package load;
  - the PLAN_V12 merge splices the cached bytes, so it no longer reads our movie's `RawData`;
  - new options: "Use Enhanced artwork", "Rebuild HUD movie" and the hidden "Enhanced folder";
  - F7 gains `hud_movie` (art, cache, timing, inputs, Enhanced folder, recognised, notes);
  - the build notes become the status line;
  - an old `GfxHUD_Minimap.upk` is logged as no longer used.
- **Tools:**
  - `release.py` builds both art variants outside the bundle, runs both real-movie suites on each, and bundles
    only the `.sdkmod` files (`release.json` schema 2 records the movies' hashes); `--game`/`--enhanced` check
    the in-mod build against real folders;
  - `install.py` installs `.sdkmod` files only and points out an old package;
  - the release workflow's notes say one-file install, and it gains a `prerelease` input.
- Versions bumped with `bump_version.py 0.13.0 --profiler-version 0.1.4`.

Evidence:
- **Real game files, `release.py --game ... --enhanced ... --profiler`:** both real-movie suites pass on both
  variants, and the mod's own build from the installed packages matches byte for byte. Enhanced art
  `5e0975c0…bbc5`, original art `267b2259…ed15`.
- **Enhanced-art movie:** 618,106 bytes, unchanged in size from v0.12.0 (the manifest version differs).
- **Original-art movie:** 617,792 bytes.
- **Release bundle `dist/releases/0.13.0`:** `classic_minimap.sdkmod` `4181461e…c013`,
  `classic_minimap_profiler.sdkmod` `370e2658…a0bd`.

Tests:
- **New:** `test_hudmovie.py` (17 cases, synthetic v584 packages); three `test_ci` original-art cases (both
  suites on the original-art fixture, the art's structure, a missing font).
- **Updated:**
  - mod-suite scenarios: a build failure leaves the minimap idle with status; the first enable builds and caches;
    a same-session re-enable reuses the movie; the next session reads the cache; the art switch and "Rebuild HUD
    movie" re-point the template; the old-package note; F7's `hud_movie`; the version-mismatch wording;
  - release and install workflow scenarios for the bundle without the package.
- **Test order:** the `test_ci`, mod-suite and workflow tests failed first for the expected reasons. The
  `hudmovie` tests were written before the module but not run red separately.
- **Results:** 128 unit tests, both real-movie suites on both variants, Ruff, actionlint and the coverage and
  repository gates all pass. Mutation testing was not run; the floors for the moved or new files are configured
  but not yet measured.

**Installed on the PC (2026-10-25 23:06 UTC, game closed):** `tools/install.py dist/releases/0.13.0 --profiler
--backups <main checkout>/dist`.
- **Installed:** `classic_minimap.sdkmod` 0.13.0 `4181461e…c013` and `classic_minimap_profiler.sdkmod` 0.1.4
  `370e2658…a0bd`, SHA-256 verified against the bundle.
- **Backups:** the previous v0.12.0 files (`cfa93923…0d45`, `988511a9…6376`) are in the main checkout's
  `dist\v0.12.0-20261025T230643.790982Z\`, with `install.json`.
- **Untouched:** the old `GfxHUD_Minimap.upk` (`a858eed8…`), which the mod now ignores (the installer pointed it
  out), and stock `GfxHUD.upk` (`5c515c3e…`). Not yet played.

Still unverified (in game):
- that GFx resolves the copied empty `WillowBody` record from the font library by name, as stock's font 119 is;
- the glyphs' size and vertical centring;
- the in-game build time, especially on the Deck (desktop CPython: about 1.2 s);
- Proton paths and the Steam library discovery on the Deck;
- the art switch and rebuild in a real session.

## 3ak. Run 21: v0.13.0 on the PC, both art variants, with Extended UI (2026-10-25)

User screenshots (Arid Badlands, "Roadkill" ready to turn in) and `unrealsdk.log` from 23:25–23:32 UTC.

What works:
- **Movie cache:** the first enable read the movie from the cache (`618106 bytes, enhanced art`).
- **Build time:** a build takes **1.84–1.92 s** in game on the PC.
- **Extended UI:** it is installed on the PC too, and the merge into its movie works with the player-built bytes
  (`template.MovieInfo` = `MinimapMergedHUD`).
- **Original art:** it renders after "Use Enhanced artwork" off plus a quit-and-load, as designed ("next level
  load"). The glyphs draw from the game font, so the copied empty `WillowBody` record resolves by name, and "N"
  and the outlined gold "X" are legible.

Findings for tuning:
1. **Duplicate turn-in marker (both arts).** At a giver whose mission is ready to hand in, two marks overlap:
   - the tracked objective's diamond, tinted gold;
   - our giver turn-in mark: Enhanced's green "?", which mostly hides the diamond, or the gold "X", which
     collides with it visibly.

   Not intended. Enhanced draws the objective slot itself as `turnin` (status 2) or `newmission` (status 0)
   instead of the diamond (ENHANCED_NATIVE.md §4, `FUN_14138d240`), so it shows one mark there.
2. **Original-art box too large:** it fills E shape 81's whole bounds (263 × 238). Those bounds include
   Enhanced's transparent margin, so a translucent panel shows well outside the window, where Enhanced shows a
   tight frame.
3. **Turn-in colour:** the gold turn-in is ours, not Enhanced's. Checked in Enhanced's HUD movie:
   - landmark sprite 112 frame `turnin` places 109 → shape 108 (fills `66FF00` green, black);
   - frame `newmission` places 111 → shape 110 (black, `FFCC00` gold "!");
   - frame `objective` places 91, a black-and-white diamond identical to classic's 1050.

   Enhanced's AS has no colour code for these (its only `Color`/`setTransform` is item-card rarity, and its HUD
   has no `SetMarkerColor`). Its edge indicator (`currentObjectiveMC`, sprite 186 → 91) follows only `objective`
   frames.

   So in Enhanced, an active objective is a white diamond, a ready turn-in is the green mark, and a new mission
   is the gold "!". Our gold turn-in and green new-mission tint of the diamond dates from v0.6 (PHASE3 §3k,
   chosen because classic's art has no such frames). It is not a v0.13 regression, but its colours are reversed
   from Enhanced's art, and decision 13's gold "X" inherited it.
4. **Art switching rebuilds every time:** each switch takes about 1.9 s, because the movie cache has one slot.
5. **The old-package note repeats** on every build.

**Fix → v0.13.1, profiler 0.1.5 (user: "match Enhanced, but keep the separate turn-in tinting as an option"):**
- **Objective style:** `objective_style()` replaces `objective_tint()`. By default the objective slots take
  Enhanced's frame from the tracked mission's status: `turnin` (2), `newmission` (0), else `objective`, all
  untinted. Turn-ins therefore get no edge diamond, as in Enhanced, since the movie's edge list holds only
  `objective` frames. The new option **"Tint objective diamonds"** (off by default) keeps the v0.6 style: the
  diamond, tinted gold or green.
- **One mark per spot:** a giver within `GIVER_OBJECTIVE_UU` (500 UU, about 10 m) of an objective adds no mark of
  its own.
- **Original art:** the "X" is green (`66FF00`, Enhanced's turn-in colour), and the box is a tight frame 5 px
  around the window.
- **Movie cache:** one slot per "Use Enhanced artwork" choice (`CACHE_NAMES`, `KEY_NAMES`).
- **Old-package note:** logged once per session.
- **Tests (each failed first):**
  - mod-suite 7c: turn-in frames untinted, two slots, no diamond; a giver on the objective adds no mark while a
    giver elsewhere does; the option's gold and green diamonds; `newmission` for a mission not started;
  - `test_ci`: the green "X", the gold "!" and the tight box bounds;
  - `test_hudmovie`: switching back reads the other choice's cache;
  - the mod suite: the note isn't repeated.
- **Real files (`release.py --game`):** the in-mod builds match. Enhanced art `9c8bb84c…3ab3`, original art
  `7825b499…a08b`; bundle `dist/releases/0.13.1` (`classic_minimap.sdkmod` `e3669056…62b5`, profiler
  `adb5d942…4287`).
- **Gates:** 129 unit tests, both real-movie suites on both variants, and the gates pass. Committed as `c4ba0d6`.

**v0.13.1 installed on the PC (2026-10-25 23:56 UTC, game closed):** `tools/install.py dist/releases/0.13.1 --profiler
--backups <main checkout>/dist`.
- **Installed:** `classic_minimap.sdkmod` 0.13.1 `e3669056…62b5` and `classic_minimap_profiler.sdkmod` 0.1.5
  `adb5d942…4287`, SHA-256 verified against the bundle.
- **Backups:** v0.13.0 (`4181461e…c013`, `370e2658…a0bd`) in the main checkout's
  `dist\v0.13.0-20261025T235646.137461Z\`.
- **Game files:** stock `GfxHUD.upk` unchanged (`5c515c3e…`). The old `GfxHUD_Minimap.upk` is no longer in the
  Interface folder (removed by the user). Played in run 22 (§3al).

## 3al. Run 22: v0.13.1 on the PC (2026-10-25 23:57–23:59 UTC)

User screenshots at Claptrap in Fyrestone and `unrealsdk.log`.

**Works:**
- **Original art turn-in:** the tracked "Get A Little Blood On The Tires" was ready to hand in at Claptrap, and
  the map showed **one** green "X" there: no gold diamond under it, no second giver mark.
- **New mission:** after the turn-in, the gold "!" for the next mission appeared at Claptrap.
- **Box:** the original art's box is a tight frame around the window.
- **Enhanced art:** after switching "Use Enhanced artwork" on and quitting to load, Enhanced's art showed.
- **The log:**
  - the original-art movie built in 2.16 s and the Enhanced movie in 1.95 s; both were cache misses, because
    0.13.1 changed the version in the key;
  - the merge into Extended UI's movie worked;
  - there were no errors or refusals;
  - the user had removed the old `GfxHUD_Minimap.upk`, so no note appeared.

**Research after run 22: zoom changes on mission switching (2026-10-26).** The user saw the zoom change when
switching the tracked mission: out when the new waypoint leads to another map, in when it is in the same map.
- **Enhanced script** (`uedis.py E`):
  - `WillowHUDGFxMovie.extInitComplete`, which runs when the HUD movie initialises (level load), is the only
    HUD path that fits: `ApplyScale`, `QuickAccessInit()`, then `AnalogScale(self, 1.0)`;
  - `WillowHUDGFxMovie.RebuildMinimapObjects`, its objective-change event, only clears and rebuilds markers
    (`ClearMapObjects`, `AS_ClearLandmarks`, `BuildMapObjects`), with no scale call;
  - `StatusMenuExGFxMovie.extInitComplete` fits the status menu's own map, and only on the quick-access screen
    (`QuickAccessScreen == 4`).
- **Enhanced native (REA, Ghidra 12.1.4 on the decoded `BorderlandsGOTY` `92b53f7f…`, evidence
  `ev_ccef4228…`):**
  - `QuickAccessInit`'s body `0x14139a970` has **no direct callers**;
  - its only references are two data words (`0x141ebae20`, `0x141ed1328`: inferred to be the vtable slots of the
    two helper classes) and unwind data;
  - native virtual calls to it are unresolved (unknown), but nothing at the script level calls it outside the
    two `extInitComplete`s.
- **Conclusion: Enhanced keeps the HUD's zoom until the next level load.** A mission switch changes the markers,
  not the zoom.
- **Our deviation:** `on_status_menu_close` calls `rebuild()`. While the map runs, that sets `rebuild_pending`,
  which clears `fit_anchor` and refits to the new mission's waypoints. Mission switching happens in the status
  menu, so every switch refits. The zoom grows for a nearby waypoint and shrinks for a far one: a waypoint
  leading to another map points somewhere distant in this one. Not a v0.13 regression; it dates from v0.10's
  "explicit rebuilds refit" combined with the status-menu hook (v0.6+).
- **Open:** what `ActiveWaypointData` holds for an objective in another map (native waypoint resolution,
  `WillowWaypoint.ResolveWaypointsFromScript`/`FindWaypoint`, not traced). It affects the level-load fit in both
  editions alike; F7's `zoom_fit.points` in such a zone answers it in game.

## 3am. v0.14.0: zoom mode (PLAN_V14 decisions 1–6; 2026-10-26, offline only)

- **"Zoom mode"** (spinner):
  - **Enhanced** (default): fits once per HUD, plus F8;
  - **Objective:** also refits when `mission_key(pc)` (the tracked mission and its status) differs from the one
    at the last fit.

  `capture` compares `S.fit_mission` with `S.mission_key` (set in `collect`).
- **Closing the status menu** now calls `rebuild(refit=False)`, which rebuilds the markers only, as Enhanced's
  `RebuildMinimapObjects` does. `rebuild()` with the default `refit=True` (F8, the markers button, option changes)
  still clears `fit_anchor`. `S.rebuild_refit` carries the choice to the next tick.
- **Renamed buttons:** "Rebuild now" is now "Refresh map markers" and "Rebuild HUD movie" is "Rebuild HUD movie
  from game files"; the merge refusal messages name the new button. The F8 keybind identifier is unchanged.
- **Test (failed first):** the mod-suite PLAN_V10 block.
  - **Enhanced:** a far waypoint plus closing the status menu keeps 185.27%, and so does a new tracked mission.
  - **Objective:** a new tracked mission refits (108%); a waypoint moving within the same mission keeps it; a
    status change refits (185.27%).
  - F8 refits, and the new button names hold.
- **Versions:** core 0.14.0, profiler 0.1.6 (`bump_version.py`).
- **Real files (`release.py --game`):** the in-mod builds match. Enhanced art `3dda7ae2…6b72`, original art
  `78740fd7…e178`; bundle `dist/releases/0.14.0` (`classic_minimap.sdkmod` `a2ea341d…f327`, profiler
  `fb723b37…1467`).
- **Gates:** 129 unit tests, both real-movie suites on both variants, and the gates pass. Committed as `da82bf4`.
- **Installed on the PC (2026-10-26 01:30 UTC, game closed):** `tools/install.py dist/releases/0.14.0 --profiler
  --backups <main checkout>/dist`.
  - **Installed:** `classic_minimap.sdkmod` 0.14.0 `a2ea341d…f327` and the profiler 0.1.6 `fb723b37…1467`,
    SHA-256 verified.
  - **Backups:** v0.13.1 (`e3669056…62b5`, `adb5d942…4287`) in the main checkout's
    `dist\v0.13.1-20261026T013034.736255Z\`.
  - **Game files:** stock `GfxHUD.upk` unchanged. Played in run 23 (§3an).

## 3an. Run 23: v0.14.0 on the PC (2026-10-26)

User screenshots: Skag Gully, Fyrestone, Sledge's Safehouse.

**Works:** the "Objective" zoom mode refits as designed (the last screenshot).

**Findings for tuning:**
1. **"Rotate with player" leaves the map icons turned:** vending machines, givers and objectives rotate with the
   map. The threat markers, the edge objective indicators and the north marker stay upright.

   Enhanced (E_HUD Minimap class, `CancelOutIconRotation`) sets `_rotation = -currentRot` on **every icon in
   `iconPathArray`** (all landmarks AddLandmark creates except the player) and on every threat. Ours counter-rotates
   only the threats (PHASE3 §3ad), so this is a gap in our port.
2. **The autosave indicator covers the minimap** (the round icon at the top right).
   - It isn't in any GFx movie. `WillowHUD` draws it natively on the canvas: class defaults `SavingMat =
     HUD.Materials.SavingIndicator_INST`, `SavingMaterialScale = 0.5`, identical in both editions.
   - Script-callable natives bracket a save: `WillowHUD.NotifySavingStarted()` and
     `NotifySavingComplete(InSaveDuration)`. Classic's exec thunk is at `0x0156a7a0`, registered at startup into
     `0x1efd278` (REA: string `intAWillowHUDexecNotifySavingStarted` at `0x1d4bff8`).
   - The draw position is in native code and wasn't traced. Ghidra has no function at the thunk, since it's
     reached only through that pointer.
   - Canvas drawing goes on top of the GFx HUD, so neither edition could cover the icon with GFx. Whether Enhanced
     moves the icon or tolerates the overlap is unknown.
3. **Angel's video is half hidden behind the minimap.** This first looked like a depth issue, but it is not one.
   - `vog` (root depth 689) sits at (412, 90) and covers stage x 412–868, the middle of the screen, so it is not
     the overlay in the screenshot.
   - The image spans stage x ≈ 960–1274, where the unshifted `echo` panel would be. But F7 snapshots show `echo`
     correctly shifted (`echo_x` 610) and `set_visible` re-applies the shift whenever the map shows.
   - Classic script: `WillowPlayerController.PlayVoGEchoCall` plays `GlobalsDef.VoGMovieDefinition` through
     `GFxUIManager.PlayMovie`. `VoGEchoCallGFxMovie.PlayEchoCall` sets the video as the external texture
     `texture1`, and the movie renders onto **`GFxUIManager.ScreenMesh`**, a 3D mesh attached to a camera actor
     (with skeletal animations from `CallDef.VoG_AnimSet`).
   - So Angel is a hologram in the 3D scene: every HUD element draws over it, and our opaque box hides the part
     behind it. Moving the map's depth would not help.
   - **Enhanced moves her by data** (the user: Enhanced shows Angel top centre). Enhanced's `GlobalsDefinition`
     adds four `Vector4` properties that classic lacks: `VoGSinglePlayerPosition`, `VoGHorizontalSplitPosition`,
     `VoGVerticalSplitPosition` and `VoG4PlayerSplitPosition`. Their values in Enhanced's
     `gd_globals.upk` (`General.Globals`; scratchpad `vogpos.py`):

     | Layout | Value |
     |---|---|
     | Single player | (−2.1, −0.4, 0.14, 0.0) |
     | Horizontal split | (−1.4, −0.65, 0.3, −0.05) |
     | Vertical split | (−1.6, −0.4, 0.3, 0.0) |
     | 4-player split | (−1.4, −0.65, 0.3, −0.05) |

     They look like camera-relative offsets of the screen mesh (inferred; Enhanced's native code that reads them
     wasn't traced). Classic's native code uses a fixed placement, which shows top right.

**→ v0.14.1, profiler 0.1.7 (2026-10-26, offline only).** The user decided: build the Angel spike and the
counter-rotation fix; leave the autosave open, without hiding the minimap.
- **Counter-rotation (movie):**
  - `add` records every icon in `_root.mmIcons`, which `MinimapClear` drops;
  - `MinimapRecenter` sets `-maps._rotation` on each icon as well as each threat, as Enhanced's
    `CancelOutIconRotation` does over `iconPathArray` and `threatsArray`;
  - the player keeps its heading.
  - Test (failed first, icon at 12° instead of −60°): `test_minimap_as` with rotation on, then north-up again.
- **Angel spike (mod):**
  - a hook on `WillowPlayerController:PlayVoGEchoCall` (POST) logs `GFxUIManager.ScreenMesh`: Translation,
    Rotation, Scale, Scale3D, AbsoluteTranslation and Owner;
  - new option **"Angel position (experiment)"**: Classic (default) or Enhanced. Enhanced calls
    `SetTranslation(Vector(-2.1, -0.4, 0.14))`, Enhanced's single-player X, Y, Z;
  - for 10 s afterwards, the tick logs any native move of the mesh and re-applies the Enhanced placement;
  - F7 gains `angel`.
  - Test (failed first, missing hook): the mod suite covers logging, applying, re-applying after a native reset,
    F7, and a missing UI manager.
- **Real files (`release.py --game`):** the in-mod builds match. Enhanced art `6d6f40ee…9e94`, original art
  `b3376a80…edee`; bundle `dist/releases/0.14.1` (`classic_minimap.sdkmod` `0f6ca48f…8d3c`, profiler
  `f4c7d39e…0147`).
- **Gates:** 129 unit tests, both real-movie suites on both variants, and the gates pass.
- **Unknown until played:**
  - whether `SetTranslation` exists on classic's screen mesh (failures are logged);
  - whether the values mean the same thing in classic's attachment;
  - whether classic's native code moves the mesh back.

  The first Angel call's log answers all three. The autosave stays open (user).
- **Committed** as `d20cdfa`.
- **Installed on the PC (2026-10-26 02:56 UTC, game closed):** `classic_minimap.sdkmod` 0.14.1 `0f6ca48f…8d3c` and the
  profiler 0.1.7 `f4c7d39e…0147`, SHA-256 verified.
- **Backups:** v0.14.0 (`a2ea341d…f327`, `fb723b37…1467`) in the main checkout's
  `dist\v0.14.0-20261026T025655.020528Z\`.
- **Game files:** stock `GfxHUD.upk` unchanged.

**Run 24 (v0.14.1, two PC sessions, 2026-10-26 03:09–03:26 UTC; logs pasted by the user):**
- **The Angel spike captured nothing.** No "Angel call" line appeared, so `PlayVoGEchoCall` never ran, and every
  F7 snapshot reported `'angel': None` (no `GFxUIManager.ScreenMesh`).
- **So the Angel the user saw is not the 3D hologram path.** Re-research:
  - classic's HUD root clip `vog` (sprite 80, depth 689) displays external image 39 named **`texture1`**, the
    name the ECHO video code sets with `SetExternalTexture("texture1", video)`;
  - Enhanced's `vog` (sprite 208, image 47) and Extended UI's merged HUD (sprite 80, image 39) are the same;
  - all three place `vog` at (412, 90), 456 × 256.6, the top centre, which is where Enhanced shows Angel;
  - the `echo` avatar's `vog` frame (sprite 211 frame 4) is only a static portrait that moves with `echo`.
- **Open:** whether classic moves `vog` at runtime (native code; no HUD AS writes it) or the top-right image is
  something else. v0.14.1's F7 doesn't record `vog`, and its hook only covers the hologram path.
- Also seen:
  - the movie cache worked across sessions (`read from the movie cache`, 0.06 s);
  - the Extended UI merge took 3.0 s;
  - Objective zoom refits on mission changes (164.6%, 151.0%, 400%) and keeps the fit otherwise.

**Not yet seen:**
- the Enhanced green turn-in mark at a ready objective (the turn-in was done in original art);
- "Tint objective diamonds" in game;
- a cache hit after switching back to an art that is already cached;
- the Steam Deck.

## 3ao. v0.14.2: Angel diagnostic for the root `vog` clip (2026-10-26, offline only)

**Why:** run 24 (§3an) showed the v0.14.1 spike watched the wrong path. The likely display is the HUD root clip
`vog`, which shows the ECHO video texture `texture1`. The classic scripts route ECHO calls through
`Behavior_PlayEchoCall` → `ServerPlayEchoCall` → native `ClientPlayEchoCall`, and the HUD side through native
`WillowHUDGFxMovie.PlayEchoCall`, so a hook alone may never fire. The diagnostic therefore reads the clip itself.

**Change (diagnostic only; no visible behaviour change):**
- F7 adds `'vog'`: the root clip's `_x`, `_y`, `_width`, `_height`, `_xscale`, `_yscale`, `_alpha`,
  `_currentframe`, `_totalframes` and `_visible`, or `None` when the movie has no `vog`.
- While the map runs, the clip is read once a second, and every change is logged as
  `Angel's screen (root vog): {…}` (one baseline line per HUD).
- Hooks on `WillowPlayerController:Behavior_PlayEchoCall`, `WillowPlayerController:ClientPlayEchoCall` and
  `WillowHUDGFxMovie:PlayEchoCall` log `ECHO call (<name>)` and read the clip every tick for 15 s.
- The v0.14.1 screen-mesh spike and "Angel position (experiment)" stay as they were.

**Tests:** a new `test_minimap_mod.py` scenario (red first: F7 had no `'vog'`):
- F7 with and without the clip;
- one baseline line and no repeats, and a moved clip is logged;
- each ECHO hook logs, and the next tick sees a change;
- after 15 s the watch is back to once a second.

Both suites pass on both art variants; 129 unit tests, coverage, ruff and the repository checks pass.
`release.py --game --enhanced`: the in-mod build matches (Enhanced art, `ba2d0256…1885`).

The first build (`bf2085a5…86ba`) was replaced before install by the run-25 fix (§3ap).

**What the next run should show:** at an Angel call, whether `vog` becomes visible and where (`_x`/`_y` near
(412, 90) = top centre as authored; a larger `_x` = moved right), and which ECHO hook, if any, fired.

## 3ap. Run 25: v0.14.1 on the Steam Deck, original art; the ECHO panel reset behind the map (2026-10-26)

**Setup (log provided by the user):** Steam Deck, v0.14.1 + profiler 0.1.7, no GOTY Enhanced (original art),
Extended UI 1.3.2. Session 03:31–05:53 UTC.
- The movie was built in 2.03 s and merged into Extended UI's movie in 3.31 s (840 386 bytes). The log noted
  the old `GfxHUD_Minimap.upk` was still on the Deck, unused.
- Zones: New Haven, Scrap caves, Interlude, Scrapyard, Pirate Bay, Trash Coast, Canyon. Every map and refit
  worked, there were no errors, and the Docked placement was 16:9 with the tilt.

**Symptom (user):** ECHO comms regularly appeared behind the minimap and its original art.

**Evidence:** four F7 snapshots, all reporting `'hud_shifted': True`, `'dock': '16:9'`, `p1` unchanged and
`'echo_x0': 791.45`:
- 05:05:05: `echo_x` 610.0 (Enhanced's place, as set);
- 05:06:47, same HUD movie: `echo_x` 791.45 (classic's authored place), with nothing logged in between;
- 05:50:38 and 05:53:15, a new HUD movie that was shifted at 05:48:23: `echo_x` 791.45 again.

The PC's run-24 snapshots were all 610.0, but that session was short.

**Cause (inferred):**
- No ActionScript in classic's or Extended UI's HUD writes `echo`'s position; the native code drives the root
  layout frames by label (`16_9`, `16_9_end`, `16_9_off`, …).
- `echo`'s place comes from p1's single first frame, so a re-played p1 puts it back while p1 itself (its
  transform and `mmOrig`) stays the same. `check_dock` sees no p1 change, so the shift was never re-applied.
- What triggers the re-play is not identified. It happened between gameplay events (probably ECHO calls), and
  run 23's "Angel half behind the minimap" may be the same reset of this panel, which shows her avatar.

**Fix (in v0.14.2):**
- New AS `MinimapHudKeep`, run by every `tick` command. While the shift is on (`mmHudMode` 1) and `p1.echo._x`
  is more than 0.5 from the shifted x, it re-applies `MinimapHudShift` with the stored placements and counts
  the fix in `mmHudFixes`.
- `MinimapHudShift` stores its placements as `_root.mmHud_<arg>` for this.
- The once-a-second dock check logs `the game put the ECHO panel back behind the map; moved it again (N
  times)`, and F7 adds `hud_fixes`.
- No extra Python-to-GFx calls per tick; one extra read per second.
- **Every frame too:** the user then reported a brief flicker of the panel behind the map before it moved,
  even with v0.14.1. That means p1 is sometimes replaced outright, and v0.14.1's once-a-second re-dock caught
  those cases late. The flicker also bounds a tick-only fix: up to 50 ms behind the map.
  `MinimapCreate` therefore sets `map.onEnterFrame = MinimapHudKeep`, so the movie checks on every frame
  before drawing it. The tick call stays as a fallback.
  - Neither HUD movie uses `onEnterFrame`, so whether this runtime fires it is unverified.
  - Expected effect: no flicker if it fires, at most one tick of flicker if not.

**Tests (red first):**
- AS: after the shift, the column is reset to authored, and the next tick puts it back (echo, quest, checklist
  scale) with `mmHudFixes` = 1. A further tick doesn't count again, and after a restore ticks leave it alone.
- AS: the map clip's `onEnterFrame` is `MinimapHudKeep`, and running it after a reset puts the column back.
- Mod: the same reset in the stubbed game is moved back on the next step and logged once; F7 has `hud_fixes`.

Both suites pass on both art variants; 129 unit tests, coverage, ruff and repository checks pass.
`release.py --game --enhanced`: the in-mod build matches (Enhanced art, `6a6ef7dd…d181`).

**Built (not installed):** `dist/releases/0.14.2/` holds `classic_minimap.sdkmod` 0.14.2 `5d2380c3…0547` and the
profiler 0.1.8 `23018d24…1139`. The earlier tick-only build `776cf659…569f` was replaced.

**Unverified:**
- the fix in game;
- whether `onEnterFrame` fires here, which would end the flicker;
- what triggers the reset.

**Committed** as `c4b5cf6`.

**Installed on the PC (2026-10-26 11:21 UTC, game closed):** `classic_minimap.sdkmod` 0.14.2 `5d2380c3…0547` and the
profiler 0.1.8 `23018d24…1139`, SHA-256 verified. v0.14.1 (`0f6ca48f…8d3c`, `f4c7d39e…0147`) is backed up in the
main checkout's `dist\v0.14.1-20261026T112120.130786Z\`. The stock `GfxHUD.upk` is unchanged (`5c515c3e…`).

**Run 26 result (§3aq):** no resets were logged on the PC; the remaining overlap is Angel's video, a different element.

**Next run:** the log should show `moved it again` lines where the panel used to stay behind the map, and F7
`hud_fixes` > 0.

## 3aq. Run 26: v0.14.2 on the PC; Angel's video is a screen particle → v0.14.3 diagnostic (2026-10-26)

**Run (PC, Enhanced art, Extended UI, Arid, 22:24–22:28 UTC; screenshot and log provided by the user):** Angel's
ECHO video (blue, glitchy) covered the area right of centre to the top right, and its right part was behind the
minimap. The user reported it as "still not adjusted properly".

**Evidence:**
- **The ECHO panel was fine.** F7 read `echo_x` 610.0 with the shift on, and `hud_fixes` was `inf` (never set), so
  the game never reset the panel in this session.
- **The ECHO hooks fired:** `Behavior_PlayEchoCall` and `ClientPlayEchoCall` at 22:27:52.
  `WillowHUDGFxMovie.PlayEchoCall` and `PlayVoGEchoCall` didn't log (native-to-native, or not used).
- **Root `vog` clip:** `_width`/`_height` 0, frame 1 of 2, visible. It didn't change during the 15 s every-tick
  watch, so it is empty and isn't Angel.
- **`'angel': None`:** there is still no `GFxUIManager.ScreenMesh`.
- The movie was built in 3.60 s (Enhanced art) and merged into Extended UI's movie in 3.03 s.

**Finding (static, classic script):** Angel's video is a **screen particle**.
- `Behavior_VoGScreenParticle` calls `ShowScreenParticle`, which creates a `ParticleSystemComponent` on the pawn:
  absolute transform, depth priority group 2, owner-only, from the behaviour's template.
- It then calls `SetUpVoGScreenParticle`, which sets the ECHO video (`CurrentEchoCall.Video`) as a texture parameter
  of the particle's material and sets its lifetime.
- It is drawn in the 3D scene, so every HUD clip, our map included, is drawn over it. Its screen position comes
  from the particle template or the component placement.
- The template lives in cooked map packages, so it can't be found by a name scan without decompressing them.

**Change → v0.14.3 + profiler 0.1.9 (diagnostic only):**
- Hooks (POST) on `WillowPlayerController:ShowScreenParticle` and `:SetUpVoGScreenParticle` log every
  `ScreenParticleRecords` entry:
  - template and material parameter;
  - component translation, rotation, scale, absolute flags, depth priority group and owner-only;
  - per emitter: name, required module (local space, screen alignment, material) and modules, with each start
    location constant.
  - `ShowScreenParticle` logs each template only once (burning or shock effects repeat).
- For 10 s after either hook, the component's translation is logged against the camera's view point once a second,
  to see whether it follows the camera.
- F7 adds `screen_particles`.

**Tests (red first):** a mod-suite scenario with a stub record (template, emitter, location module, component)
checks:
- the dump and the camera comparison line;
- F7's field;
- `ShowScreenParticle` logging a repeated template once;
- no crash without `ScreenParticleRecords`.

Both suites pass on both art variants; 129 unit tests, coverage, ruff and repository checks pass.
`release.py --game --enhanced`: the in-mod build matches (`3d5b2638…e0a1`).

**Built (not installed):** `dist/releases/0.14.3/` holds `classic_minimap.sdkmod` 0.14.3 `48d426bb…d8fc` and the
profiler 0.1.9 `2c63f50f…b60f`.

**Committed** as `187392d`.

**Installed on the PC (2026-10-26 22:35 UTC, game closed):** `classic_minimap.sdkmod` 0.14.3 `48d426bb…d8fc` and the
profiler 0.1.9 `2c63f50f…b60f`, SHA-256 verified. v0.14.2 (`5d2380c3…0547`, `23018d24…1139`) is backed up in the
main checkout's `dist\v0.14.2-20261026T223549.859286Z\`. The stock `GfxHUD.upk` is unchanged (`5c515c3e…`).

**Run 27 result and the next step:** §3ar.

**Next:** at Angel's next call, read the dump. Moving her video needs one of these, which the dump should show:
- the component follows the camera and has an offset we can change;
- a location module whose start location sets the offset;
- or a material or screen-alignment setting that places it in screen space.

## 3ar. Run 27: v0.14.3 on the PC, Angel's particle dumped → v0.14.4 placement experiment (2026-10-26)

**Run (PC, Enhanced art, Extended UI, Arid, 22:37–22:38 UTC; log only):** one Angel call at 22:37:53. Three F7s
were taken during the call (two) and after it (one, `screen_particles: []`).

**Dump:**
- **Template:** `ParticleSystem'fx_PostProcess.VoG.part_VoG_Pulse'`, material parameter `VoGMaterial`.
- **Component:**
  - At `ShowScreenParticle`: translation (0, 0, 0).
  - During the call: translation (−16831.3, 31912.1, −81.9), rotation (−5894, −3997, 0), scale 15.93.
  - Flags: absolute translation, rotation and scale; `SDPG_Foreground`; owner-only.
- **Camera** (still for 6 s): (−17072.3, 32009.3, 83.0).
  - The offset (241.0, −97.2, −164.9) is 307.8 units long, at yaw −21.96° and pitch −32.4°. Those are exactly the
    component's rotation.
  - So the engine places the effect on a ray out from the camera, along the component's rotation (most likely the
    camera's own rotation), and scales it by 15.93.
- **Emitter `Main_VOG`:** local space, `PSA_Rectangle` (camera-facing), material
  `fx_PostProcess.VoG.VoG_Mati`.
  - Modules: `ParticleModuleLocation` (cooked: `StartLocation.Distribution` is None), `Size`, `Lifetime`, `Color`,
    `ColorScaleOverLife`, `MaterialByParameter`.
  - `ScreenParticleModifier` holds only `ScalarParams` (material parameters), so it doesn't place the effect.

**Inference:** with the component on the view axis, her top-right placement comes from the emitter's local start
location (X forward, Y right, Z up). It is baked into `StartLocation.LookupTable`, which v0.14.3 didn't print.
The camera rotation wasn't logged either, so "component rotation = camera rotation" is still unconfirmed.

**Change → v0.14.4 + profiler 0.1.10:**
- **Logging:** the dump prints each start location's lookup table (`dist`, `op`, `chunk`, `table`), and the watch
  lines add the component's and the camera's rotation.
- **"Angel position (experiment)" = Enhanced** now acts on this particle. A PRE hook on `ShowScreenParticle`
  edits the template before the effect starts:
  - only templates whose name contains `VoG`;
  - it zeroes the Y (sideways) value of every lookup-table entry (index 2 + k·chunk + 1, and + 4 for min/max
    entries), which should centre her horizontally at the same height, like Enhanced's top centre;
  - it keeps the original table, and Classic restores it on the next call.
  - The edit is in memory only (no game file changes), and it logs before → after once.
- The option's description now says "centred at the top, like GOTY Enhanced… applies from her next call". The
  ScreenMesh part of the v0.14.1 spike stays but never fires in classic.
- The test stubs register hooks by name and type (`name:pre` / `name:post`). UObject stand-ins (`Obj`) print as
  their path, like pyunrealsdk objects.

**Tests (red first):**
- the lookup-table dump and the rotation watch line;
- Enhanced zeroes Y once (idempotent) and handles 3- and 6-float entries;
- a non-VoG template is untouched;
- Classic restores the table.

Both suites pass on both art variants; 129 unit tests, coverage, ruff and repository checks pass.
`release.py --game --enhanced`: the in-mod build matches (`00928658…860f`).

**Built (not installed):** `dist/releases/0.14.4/` holds `classic_minimap.sdkmod` 0.14.4 `4a6d7886…a9ed` and the
profiler 0.1.10 `84ab5543…c2de`.

**Unverified:**
- whether the lookup table holds the offset and Y is the sideways axis;
- whether pyunrealsdk's struct access edits the template in place (the code also writes the struct back);
- whether an edited table survives a level load (it re-applies every call).

**Committed** as `ef478e1`.

**Installed on the PC (2026-10-26 22:45 UTC, game closed):** `classic_minimap.sdkmod` 0.14.4 `4a6d7886…a9ed` and the
profiler 0.1.10 `84ab5543…c2de`, SHA-256 verified. v0.14.3 (`48d426bb…d8fc`, `2c63f50f…b60f`) is backed up in the
main checkout's `dist\v0.14.3-20261026T224549.606761Z\`. The stock `GfxHUD.upk` is unchanged (`5c515c3e…`).

**Next run:** set "Angel position (experiment)" to Enhanced, trigger an Angel call, and check her position and the
`Angel's video centred` line.

## 3as. Run 28: v0.14.4 on the PC; Angel's particle is on the view axis → v0.14.5 material dump (2026-10-26)

**Run (PC, Arid, 22:49 UTC; log only):** the user reported "it didn't work".
- **The experiment never ran:** the saved option was still `Classic`, and there was no `Angel's video centred`
  line.
- **It couldn't have worked anyway:** the location module's table is `[0.0, 0.01, 0.01, 0.0, 0.0, 0.01, 0.0, 0.0]`
  (op 1, chunk 3). Both entries are ≈ (0.01, 0, 0), so the emitter has no sideways start offset to remove.

**Evidence from the watch lines:**
- **The component's rotation equals the camera's:** (−3349, −32593, 0).
- **It sits on the view axis.** The offset from the camera is (−494.3, −8.2, −164.5), 521 units at yaw −179.05°
  and pitch −18.4°, which is the camera's own direction.
- **Distance scales with size:** 521 / 26.98 = 307.8 / 15.93 (run 27) = 19.3.
- So the native code places the particle at screen centre, scaled to the view, and her top-right placement must
  come from the material: VoG_Mati or its parent, through screen-space UVs or parameters.

**Change → v0.14.5 + profiler 0.1.11 (diagnostic):**
- **Material dump:** the record now includes the per-call material instance (the PSC's `InstanceParameters` entry
  named by `MatParamName`), and the emitter's `Material`. Each is dumped as name, class, scalar/vector/texture
  parameters and parent chain (up to 4 levels).
- **Modules:** the dump adds the `StartSize`, `StartVelocity` and `Lifetime` tables.
- **The option:** the v0.14.4 Y-zero code stays but is a known no-op. Its description now says the experiment
  "has no visible effect yet".

**Tests (red first):** the size table, the instance and template materials with scalar, vector and texture
parameters, and the parent chain reaching the base material. Both suites pass on both art variants; 129 unit
tests, coverage, ruff and repository checks pass. `release.py --game --enhanced`: the in-mod build matches
(`2123bbc0…42e8`).

**Built (not installed):** `dist/releases/0.14.5/` holds `classic_minimap.sdkmod` 0.14.5 `45828006…1191` and the
profiler 0.1.11 `c4b1d19f…f7d5`.

**Committed** as `1b9a6af`.

**Installed on the PC (2026-10-26 22:56 UTC, game closed):** `classic_minimap.sdkmod` 0.14.5 `45828006…1191` and the
profiler 0.1.11 `c4b1d19f…f7d5`, SHA-256 verified. v0.14.4 (`4a6d7886…a9ed`, `84ab5543…c2de`) is backed up in the
main checkout's `dist\v0.14.4-20261026T225604.292541Z\`. The stock `GfxHUD.upk` is unchanged (`5c515c3e…`).

**Next:** at Angel's next call, look for a position-like scalar or vector parameter (offset, UV, screen position),
which could be set on the per-call instance. If there is none, the placement is in the material graph: compare
Enhanced's handling, or consider a different fix.

## 3at. Run 29: v0.14.5 on the PC; the material has no position → v0.14.6 shifts the overlay (2026-10-26)

**Run (PC, Arid, 23:03 UTC; log only):** "Angel position (experiment)" was set to Enhanced this time.
- The v0.14.4 edit ran before the effect started (`Angel's video centred` came before `ShowScreenParticle`), but
  it changed nothing: Y was already 0.

**Dump:**
- **Per-call material instance** (`…ParticleSystemComponent_156.MaterialInstanceConstant_224`): it only sets the
  texture `VoGMovie` to `TextureMovie'vog_binks.HiQuality.Vog_170-ALT_PostLook'`, the call's video.
- **Parent `fx_PostProcess.VoG.VoG_Mati`:** scalars `ScanLinesAmount` 0.2 and `StaticAmount` 0.8, and the default
  `VoGMovie` (`Vog_1a-ALT_V02_PostLook`).
- **Base `Material'fx_PostProcess.VoG.VoG_Master_Shader'`:** no parameters.
- **`StartSize`:** `[0.0, 17.76, 17.76, 10.0, 0.0, 17.76, 10.0, 0.0]`, a 17.76 × 10 (16:9) sprite. `Lifetime` is
  a particle parameter (VoGMovieDuration).
- **Component:** on the view axis again (rotation = camera's (−3273, −32249, 0); 527 units; scale 27.59; ratio
  19.1).

**Conclusion:**
- There is no position parameter anywhere in the material chain.
- The particle is a 16:9 overlay centred on the view, from `fx_PostProcess`.
- The "PostLook" videos must draw Angel in their own top-right corner. In run 26's screenshot she spans about
  65–85% of the width (centre ≈ 75%) and 0–30% of the height.
- So moving her means moving the whole overlay. Shifting it left by a quarter of its width (if it about fills the
  screen) puts her centre at ≈ 50%: top centre, like Enhanced.

**Change → v0.14.6 + profiler 0.1.12:**
- **"Angel position (experiment)" = Enhanced** subtracts `0.25 × overlay width` from the Y (sideways) value of each
  start-location entry of VoG templates, before the effect starts (PRE `ShowScreenParticle`). The width is read
  from the template's `StartSize` X, or 17.76.
  - For Main_VOG that is −4.44, logged as `Angel's video moved left by 4.44: …`.
  - Classic restores the authored values; the edit is in memory only.
- The option's description is back to promising the move ("shifted to the top centre, like GOTY Enhanced.
  Experimental; applies from her next call").

**Tests (red first):** the stubs now use the real run-28/29 tables. The checks:
- Enhanced shifts Y by −4.44 once (idempotent), for both 3- and 6-float entries;
- a non-VoG template is untouched;
- Classic restores the table.

Both suites pass on both art variants; 129 unit tests, coverage, ruff and repository checks pass.
`release.py --game --enhanced`: the in-mod build matches (`8924ba37…dc43`).

**Built (not installed):** `dist/releases/0.14.6/` holds `classic_minimap.sdkmod` 0.14.6 `e4fbda70…0ee1` and the
profiler 0.1.12 `3f748e50…e33f`.

**Unverified:**
- that the overlay about fills the screen, so a quarter of its width is a quarter of the screen;
- that +Y is screen-right in this local space;
- the vertical position (unchanged).

If she lands off-centre, the logged shift and her new position give the scale for one adjustment.

**Committed** as `b9072eb`.

**Installed on the PC (2026-10-26 23:08 UTC, game closed):** `classic_minimap.sdkmod` 0.14.6 `e4fbda70…0ee1` and the
profiler 0.1.12 `3f748e50…e33f`, SHA-256 verified. v0.14.5 (`45828006…1191`, `c4b1d19f…f7d5`) is backed up in the
main checkout's `dist\v0.14.5-20261026T230836.401181Z\`. The stock `GfxHUD.upk` is unchanged (`5c515c3e…`). The
user's "Angel position (experiment)" is already Enhanced.

## 3au. Run 30: v0.14.6 moves Angel to the top centre → v0.14.7 "Angel position", Classic / Centered (2026-10-26)

**Run (PC, Arid, 23:09 UTC; screenshot and log provided by the user):** "It's not perfectly centered, but it
WORKED".
- The log has `Angel's video moved left by 4.44` before the effect started, and the table entries' Y read −4.44.
- In the screenshot Angel spans about 820–1300 px of 2000 (centre ≈ 53%), at the top and clear of the minimap.
- The last watch line shows the component's rotation following the camera's, (−3669, −32012) → (−2881, −30917),
  so the game keeps the overlay on the view and the shift holds while looking around.
- distance/scale = 476.8 / 24.69 = 19.3, as in runs 27–29.

**Tuning:** 0.25 of the width (4.44) moved her from ≈ 75% (run 26) to ≈ 53%, about 5% of the screen per unit.
Centring needs about 0.6 more: 0.28 of the width, 4.97 for Main_VOG.

**Are some Angel calls already centred? (user's question):**
- **Videos:** `WillowGame\Movies` has 14 `NAR_Echo_Vog_*-ALT_PostLook*.bik`.
  - Bink headers: 11 are 284×160 at 30 fps; `Vog_1a` (the template default, her first contact) and `Vog_83` are
    746×420; `Vog_70…_C` is 160×90 at 13 fps.
  - Frames decoded with a static ffmpeg 9.0.2 (gyan.dev essentials, SHA-256 checked, in `C:\Users\Charles\Tools\
    ffmpeg`; downloaded with the user's permission): all 14 are full-frame portraits, brightness centre x 0.48–0.56,
    y 0.46–0.50.
  - So no video places Angel differently: classic's top-right offset is the overlay's, the same for every call.
    Contact sheets were checked for Vog_170 and Vog_83.
- **Templates:** `fx_PostProcess.upk` (uncompressed) holds two VoG particle systems, `part_VoG_Pulse` (seen in
  every run) and `part_VoG_SimpleFade`.
  - Neither sets an emitter origin, and both start at location ≈ 0.
  - SimpleFade's LOD0 overlay is 20 × 10. Its LOD1 adds a small random location (0.01, −2…0, −2…0.5) and size jitter.
  - The shift is a fraction of each template's own width, so SimpleFade would get 5.6. Which behaviour uses it is
    unknown (cooked map packages).
- **The full-screen Angel movies** (`VoG_Transition_Movie`, 1280×720) play through `Movie_Play` at story points,
  not this overlay, so the mod doesn't touch them. These are likely the "centred" calls the user remembers.

**Invariance (user's question):**
- **Holds:** the overlay, classic's unexplained offset and our shift are all in the particle's local space. The
  game keeps that on the view axis, rotated with the camera, at distance ≈ 19.3 × scale (runs 27–30), so it fills
  a fixed angle of the view whatever the scale, distance or camera direction.
- **Could break:** a different FOV (aiming down sights, `fov`) or aspect ratio (Deck 16:10, 4:3).
  - If classic's offset is in local space, the shift cancels it at any FOV.
  - If it is a screen-space offset, the shift only cancels it at the tested FOV.
- v0.14.7 logs the FOV and distance/scale on every watch line, so screenshots under those conditions can settle it.

**Change → v0.14.7 + profiler 0.1.13:**
- **The option** is now **"Angel position"** with **Classic / Centered**, default Centered (the user chose the
  American spelling).
  - Its description: "Centered: top centre, clear of the minimap, like GOTY Enhanced. Classic: top right, partly
    behind the minimap. Applies from her next call."
  - The rename resets saved values once. README updated.
- **The shift** is `VOG_SHIFT` 0.28.
- **The v0.14.1 screen-mesh spike's move is retired** (`VOG_ENHANCED`, `apply_vog_position`), since classic never
  used the mesh. Its logging stays, now logging "the screen mesh moved to …".
- **Watch lines** add `fov` (`GetFOVAngle`) and `distance/scale`.

**Tests (red first):**
- Centered is the default; the mesh is never moved, and a native move is logged;
- Centered shifts the real Pulse table by −4.97 once, and a 6-float table without a size module by 4.97;
- Classic restores the table;
- the watch line has FOV and distance/scale.

Both suites pass on both art variants; 129 unit tests, coverage, ruff and repository checks pass.
`release.py --game --enhanced`: the in-mod build matches (`d2fc0fa9…275f`).

**Built (not installed):** `dist/releases/0.14.7/` holds `classic_minimap.sdkmod` 0.14.7 `cca615b0…6664` and the
profiler 0.1.13 `9a15ba1f…cda9`.

**Committed** as `5c06890`.

**Installed on the PC (2026-10-26 23:46 UTC, game closed):** `classic_minimap.sdkmod` 0.14.7 `cca615b0…6664` and the
profiler 0.1.13 `9a15ba1f…cda9`, SHA-256 verified. v0.14.6 (`e4fbda70…0ee1`, `3f748e50…e33f`) is backed up in the
main checkout's `dist\v0.14.6-20261026T234610.240604Z\`. The stock `GfxHUD.upk` is unchanged (`5c515c3e…`).

**To confirm invariance (next runs):** screenshot Angel's calls in each condition, each with the matching watch
lines:
- normal play;
- aiming down sights during a call;
- `fov 110` in the console;
- the Steam Deck at 16:10;
- a later mission's call, to see a different video and maybe SimpleFade.

## 3av. Run 31: v0.14.7 on the PC; Angel centred and stable across iron sights (2026-10-27)

**Run (PC, Arid, 01:24 UTC; screenshot and log provided by the user):** "looked good… it seemed to be stable between
ironsights and normal fov". Sprint FOV was not tried.

**Evidence:**
- The log has `Angel's video moved left by 4.97` (table Y −4.97) before the effect started. Default Centered
  applied with no settings change, as expected after the rename.
- In the screenshot Angel spans about 830–1250 px of 2000 (centre ≈ 52%), level with the centred objective text and
  clear of the minimap.
- **Watch lines:** `fov` 70.0 normally, and 48.3 and 53.0 in iron sights. `distance/scale` stayed 19.31 throughout,
  and the component scale barely moved (27.67 → 27.31 → 27.24).
  - So the native code doesn't resize the overlay for the FOV, yet the user saw no shift when zooming.
  - This fits the component's `SDPG_Foreground` depth group: UE3 draws the foreground (first-person weapon) layer
    with its own projection, independent of the zoom. That part is inferred; the in-game observation is the
    evidence.
- **The gun scope is also a screen particle** (`fx_PostProcess.Particles.fx_part_All_Round_GunScopes`, parameter
  `WeaponScopeMaterial`). It sits at the same translation, rotation and scale as Angel's overlay, so the native
  placement is the engine's general screen-particle rule. Its name has no "VoG", so the mod leaves it alone. It
  was logged once, as designed.
- The ECHO panel stayed shifted (`echo_x` 610; no resets).

**Invariance status:**
- **Confirmed:** camera direction (run 30), iron-sights FOV 48–53 vs 70 (run 31), and every Pulse video (frame
  analysis, §3au).
- **Not yet seen:** sprint FOV, the Deck's 16:10 aspect, 4:3, and a call that uses `part_VoG_SimpleFade`.

No code change.

## 3aw. Run 32: v0.14.7 on the Steam Deck, original art, FOV 100 (2026-10-27)

**Run (Deck, 02:15–02:18 UTC; log provided by the user):** "steam deck test successful".
- Setup: no GOTY Enhanced, so original art. Extended UI 1.3.2 alongside other SDK mods, including "FOV and sprint
  rotation fix" 3.0.0, Unofficial Patch 1.3.3, Playthrough 3 and Repeatable Missions.

**Evidence:**
- The movie was built in 2.20 s (619 135 bytes, original art, Proton `S:\` paths) and merged into Extended UI's
  movie in 3.74 s (841 359 bytes). Docked at 16:9 with the tilt; map ready at Arid with 26 markers; no errors from
  the mod.
- **Angel:** `Angel's video moved left by 4.97` came before the effect started, and the user reports success.
- **Watch lines:** `fov 100.0` (the FOV mod) and **`distance/scale 15.37`**, against 19.31 at FOV 70 on the PC;
  the component scale was 63.7.
  - So the native code re-places the overlay for a different base FOV, unlike the transient iron-sights zoom in run
    31, where the ratio stayed 19.31.
  - The local-space shift still put her where the user expected. This covers both a large FOV change and the
    Deck's display in one run.
- **ECHO panel:** `echo_x` 610, `hud_shifted` True; no `moved it again` lines in this short session.
- The log still notes the old `GfxHUD_Minimap.upk` on the Deck; it is unused and can be deleted.

**Invariance status:**
- **Confirmed:** camera direction (run 30), iron-sights zoom (run 31), base FOV 100 on the Deck (run 32), and
  every Pulse video (§3au).
- **Not yet seen:** 4:3, and a call using `part_VoG_SimpleFade`.

No code change.

## 3ax. v0.14.8: autosave indicator diagnostic (2026-10-27, offline only)

**Why:** with Angel fixed, the user asked to revisit the autosave icon that covers the minimap (run 23, §3an; left
open by the user's decision then) and chose to diagnose before picking a fix.

**Research (static):**
- **Neither edition has a position property for the icon.** Classic's `WillowHUD` has only `SavingMat`
  (`HUD.Materials.SavingIndicator_INST`) and `SavingMaterialScale` (0.5), plus the timing fields `SaveStartTime`
  and `SaveDuration`. Enhanced has the same, with `ConnectionMat` and the connection-warning fields alongside.
- The draw position is fixed in native code, so unlike Angel's particle (§3au) it can't be moved by editing data.
- Neither HUD movie (classic or Enhanced) has save-indicator art.
- The options weighed with the user:
  - replace the native icon with our own GFx indicator, timed from `SaveStartTime`/`SaveDuration`;
  - shrink it through `SavingMaterialScale` (anchor unknown);
  - diagnose first (chosen);
  - leave it.

**Change → v0.14.8 + profiler 0.1.14 (diagnostic only; no visible change):**
- Every 0.25 s the mod reads `SaveStartTime`, `SaveDuration`, `SavingMaterialScale` and `SavingMat` from
  `pc.myHUD`. It logs `save indicator: {…}, 'world_time': …` on every change, with one baseline line per HUD.
- F7 adds `save_indicator`.
- PRE hooks on `WillowHUD:NotifySavingStarted` and `:NotifySavingComplete` log whether they ever fire. They are
  natives called from native code, so they may not, like `PlayEchoCall` (§3ap).

**Tests (red first):**
- one baseline line and no repeats, with world time and the material;
- changes to `SaveStartTime` and `SaveDuration` are logged;
- both hooks log;
- F7 has the field;
- a HUD without the fields doesn't crash.

Both suites pass on both art variants; 129 unit tests, coverage, ruff and repository checks pass.
`release.py --game --enhanced`: the in-mod build matches (`323b5b38…c92c`).

**Built (not installed):** `dist/releases/0.14.8/` in the `feat/save-indicator-diag` worktree holds
`classic_minimap.sdkmod` 0.14.8 `96cd97a2…4178` and the profiler 0.1.14 `e36949c8…8743`.

**Committed** as `764746c` on `feat/save-indicator-diag`.

**Installed on the PC (2026-10-27 23:17 UTC, game closed):** `classic_minimap.sdkmod` 0.14.8 `96cd97a2…4178` and the
profiler 0.1.14 `e36949c8…8743`, SHA-256 verified. v0.14.7 (`cca615b0…6664`, `9a15ba1f…cda9`) is backed up in the
main checkout's `dist\v0.14.7-20261027T231716.560310Z\`. The stock `GfxHUD.upk` is unchanged (`5c515c3e…`).

**Next run:** trigger an autosave (enter a new area, or complete or turn in a mission) and take a screenshot while
the icon shows. The log gives how `SaveStartTime`/`SaveDuration` move against world time. The screenshot gives
the icon's exact spot and size against the minimap. Together they decide between our own indicator and a smaller
native one.

## 3ay. Run 33: v0.14.8 on the PC; how an autosave drives the HUD fields (2026-10-27)

**Run (PC, Enhanced art, Extended UI, New Haven, 23:49–23:50 UTC; log provided by the user, no screenshot):** the
user drove past several autosave stations and pressed F7, noting that perhaps only the last one showed the icon.

**Evidence:**
- **Baseline:** `SaveStartTime` 0.0, `SaveDuration` 0.0, `SavingMaterialScale` 0.5, `SavingMat`
  `HUD.Materials.SavingIndicator_INST`.
- **One save, at 23:50:39** (in the vehicle): `SaveStartTime` 69.856 and **`SaveDuration` 3.0**. About 2.9 s later
  (23:50:42) `SaveDuration` was back to **0.0**, with `SaveStartTime` unchanged.
  - No other changes: the earlier stations didn't save, as the user suspected. Read every 0.25 s, a 3 s window
    can't be missed.
- **Clock:** `SaveStartTime` (69.86) runs ahead of `WorldInfo.TimeSeconds` (61.98), so it uses another clock,
  probably real or audio time. `SaveDuration > 0` alone marks when the icon is showing.
- **Hooks:** `NotifySavingStarted`/`Complete` never fired. They are native-to-native, like `PlayEchoCall`.
- **Side result: v0.14.2's ECHO fix seen working on the PC.**
  - The log reads `the game put the ECHO panel back behind the map; moved it again` (1, then 2 times, at
    23:50:08–09), and F7 reads `hud_fixes` 2.0 with `echo_x` 610.
  - That is the first in-game proof of the run-25 fix: the reset happens on the PC too.

**Not captured:** a screenshot of the icon's position. It isn't needed for a replacement.

**Next:** choose the fix (§3ax options). With the timing known, a replacement can:
- hide the native icon (`SavingMaterialScale` 0, which avoids a None material);
- show our own indicator while `SaveDuration > 0`.

**Decided (PLAN_V15):** reuse the game's texture and its pulse in our movie, left of the map like the ECHO panel
(overlap with an active call is fine, as in classic), with a "Saving..." text fallback and no option.

## 3az. v0.15.0: PLAN_V15 step 1, the save indicator spike (2026-10-27, offline only)

**Change → v0.15.0 + profiler 0.1.15. Both icons show during a save, so one screenshot measures the native spot.**

- **Movie** (`swfbuild.save_art`, both art variants):
  - `DefineExternalImage` 1330 `mmSaveTex` (128 × 128, format 13), laid out like classic's eight controller-button
    placeholders;
  - shape 1331, clipped-bitmap filled from it, centred, one bitmap pixel per px;
  - a copy of the HUD's (empty) WillowBody font (1333) and a "Saving..." DefineEditText (1332, 40 px, white);
  - sprite 1334 holding `icon` and `label`, exported `bl1mm_save`.
- **AS:**
  - `save~mode~x~y~size` calls `MinimapSave`, which attaches `_root.mmsave` once at depth 9002 (above the map),
    places and scales it, and shows the texture (1), the text (2) or nothing (0). `icon.blendMode = "add"`, like
    the native `BLEND_Additive`.
  - `MinimapSavePulse` (its `onEnterFrame`) pulses `_alpha` 10–100 % on a sine. The step is 2π / (HUD fps × 1 s),
    baked in from the HUD header.
  - `MinimapDestroy` removes the clip.
- **Mod:**
  - Once per HUD it finds `Texture2D'HUD.Textures.saving_indicator'` and binds it with
    `movie.SetExternalTexture("mmSaveTex", tex)`.
    - If the texture isn't loaded, it retries every 5 s and shows the text meanwhile.
    - If the call raises, it falls back to the text and doesn't retry.
  - While `SaveDuration > 0`, with the map docked and shown, it shows ours at the ECHO panel's shifted spot
    (provisional), 48 px. It logs `save icon shown (texture|Saving...) at …` and `hidden`. F7 adds `save_icon`.
  - **The native icon is left alone in this build.**
- **Test fixture:** `test_ci`'s gradient fixture HUD now carries the WillowBody font, like the real HUD. The
  Enhanced-art build copies it for the label too.

**Tests (red first):**
- AS: attach once; hiding never attaches; placement and scale; texture or text; additive blend; pulse range;
  hide; destroy removes it.
- Builder: the external image's bytes, the shape's bitmap fill, the font and text, the export, and the named
  children.
- Mod: texture missing → text → bound on retry → texture; hidden after the save; hidden while the minimap is;
  binding raises → text, logged once; F7; native scale untouched.

Both suites pass on both art variants; 129 unit tests, coverage, ruff and repository checks pass. An offline merge
into Extended UI's HUD movie keeps ids 1330–1334 and the export, with no clash. `release.py --game --enhanced`:
the in-mod build matches (`685f7e97…2787`).

**Built (not installed):** `dist/releases/0.15.0/` in the `feat/save-indicator-diag` worktree holds
`classic_minimap.sdkmod` 0.15.0 `b5e8312e…3c8c` and the profiler 0.1.15 `512233be…ea42`.

**Unverified (in game):**
- whether `SetExternalTexture` from Python is safe and returns True;
- whether GFx draws the `G8` texture additively (no grey or black square);
- the pulse's look;
- that both icons show during a save.

**Committed** as `adee2a4` on `feat/save-indicator-diag`.

**Installed on the PC (2026-10-28 00:58 UTC, game closed):** `classic_minimap.sdkmod` 0.15.0 `b5e8312e…3c8c` and the
profiler 0.1.15 `512233be…ea42`, SHA-256 verified. v0.14.8 (`96cd97a2…4178`, `e36949c8…8743`) is backed up in the
main checkout's `dist\v0.14.8-20261028T005833.795878Z\`. The stock `GfxHUD.upk` is unchanged (`5c515c3e…`).

**Next run:** trigger an autosave and take a screenshot while both icons show. Step 2 then sets our spot to the
native spot plus the ECHO shift and hides the native icon.

## 3ba. Run 34: v0.15.0 on the PC; the texture didn't bind → v0.15.1 (2026-10-28)

**Run (PC, Enhanced art, Extended UI, New Haven, 01:47–01:49 UTC; log provided by the user, no screenshot):** "the
fallback 'Saving...' was cropped as 'Savinq...', but it did trigger with the autosave marker".

**Evidence:**
- **Timing works.** At the save (`SaveDuration` 3.0 at 01:49:27) the mod logged `save icon shown (Saving...) at
  (826.0, 43.5)`, then `save icon hidden` at 01:49:30 when the native icon went away. The user saw both.
- **Binding:** `save icon texture bound: False (Texture2D'HUD.Textures.saving_indicator')`.
  - The texture was found, and `SetExternalTexture` returned False without raising.
  - So calling it from Python is safe (no crash), but nothing was bound, and the text fallback showed. F7 read
    `save_icon {'bound': False, 'mode': 2}`.
- **Label:** "Saving..." was clipped to "Savinq...". The text box ended 0.6 × the font size below its origin and
  cut the "g"'s descender.
- The ECHO reset fix fired twice again (01:48:23–25).

**Cause of the False:** every external image the classic HUD binds at runtime is also listed in the movie's
ExportAssets under the same name:
- `texture1` (the ECHO video, 64 × 64);
- `weaptex1..4` and `p2_weaptex1..4`;
- the 30 controller-button images.

Images that are never bound (`HUD_IB6.tga`, …) have an empty name and no export. Our `mmSaveTex` had its name
inside the tag but no export entry. GFx's `SetExternalTexture` evidently resolves the name through the export table.

**Change → v0.15.1 + profiler 0.1.16:**
- The block's ExportAssets lists `(1330, 'mmSaveTex')`.
- The label box spans −0.45 … +0.8 × the font size, the proportions of the map glyphs' boxes.

**Tests (red first):**
- AS/builder: the placeholder is exported under its name, and the label box reaches 0.8 × the font size below its
  origin.

Both suites pass on both art variants; 129 unit tests, coverage, ruff and repository checks pass. The offline
Extended UI merge keeps ids 1330–1334 and the exports. `release.py --game --enhanced`: the in-mod build matches
(`09cb239d…5ee6`).

**Built (not installed):** `dist/releases/0.15.1/` in the `feat/save-indicator-diag` worktree holds
`classic_minimap.sdkmod` 0.15.1 `0d074f7e…4b43` and the profiler 0.1.16 `f3c9ddb6…ea09`.

**Committed** as `b27e776` on `feat/save-indicator-diag`.

**Installed on the PC (2026-10-28 02:40 UTC, game closed):** `classic_minimap.sdkmod` 0.15.1 `0d074f7e…4b43` and the
profiler 0.1.16 `f3c9ddb6…ea09`, SHA-256 verified. v0.15.0 (`b5e8312e…3c8c`, `512233be…ea42`) is backed up in the
main checkout's `dist\v0.15.0-20261028T024022.335811Z\`. The stock `GfxHUD.upk` is unchanged (`5c515c3e…`).

**Next run:** an autosave with a screenshot.
- The log should read `save icon texture bound: True` and `shown (texture)`.
- The screenshot shows how the G8 texture draws with the additive blend, and the native icon's spot for step 2.

## 3bb. Run 35: v0.15.1 on the PC; the texture binds but draws opaque (2026-10-28)

**Run (PC, Enhanced art, Extended UI, New Haven, 02:42–02:45 UTC; log and three screenshots provided by the user):**
"it loaded that time, but without an alpha channel. it also pulsed out of sequence with the native one".

**Evidence:**
- **Binding works:** `save icon texture bound: True (Texture2D'HUD.Textures.saving_indicator')`, then `save icon
  shown (texture) at (826.0, 43.5)`, hidden when `SaveDuration` returned to 0. Three saves (02:43:27, 02:45:08,
  02:45:26) all showed and hid.
- **No transparency:** ours draws the white Vault logo on a solid black 48 px square (screenshots 1–3, top centre).
  - GFx ignored the AS `blendMode = "add"`.
  - None of the game's three movies (classic HUD, Enhanced HUD, status menu) uses a blend mode anywhere, in
    PlaceObject3 or AS (`blendscan.py`). Their bound images rely on textures with real alpha, so additive blending
    is a dead end in this GFx.
- **The native icon's spot** (screenshots 2–3, 2000 × 1125): over the middle of the docked minimap, centred about
  (1750, 160) px, about 100 px wide. That is stage ≈ (1120, 102), about 64 stage px.
- **The pulse is out of step.** The material (`matgraph.py`) gives emissive = texture × `Clamp(OneMinus(Sine(Time)),
  0, 1)` × `MatAlpha` (1), with Time ignoring pause and the Sine period the default 1 s.
  - So brightness = clamp(1 − sin(2πt), 0, 1) on the engine's real-time clock: full for half of each second, dark
    at t mod 1 = 0.25.
  - Ours ran a frame-counted sine from the moment it appeared.
- **Side notes:**
  - The ECHO reset fix fired twice again.
  - The gun-scope screen particle was logged at FOV 25.7 (scoped) with distance/scale 15.37. Once the scope closed,
    the component sat at the origin, a stale record before `HideScreenParticle`.

**Open for step 2 (user's choice):** how to get transparency, since the game texture can't be drawn additively.
The native spot and the pulse formula are now known.

**Decided:** a vector redraw (PLAN_V15 step 2).

## 3bc. v0.15.2: PLAN_V15 step 2, our own save indicator replaces the native one (2026-10-28, offline only)

**Change → v0.15.2 + profiler 0.1.17:**
- **Art** (`swfbuild.save_art`, both art variants): the game's Vault logo redrawn as our own vector art, white, in a
  128 px box.
  - The ring is shape 1330: outer radius 60, inner 48, 48 sides. Both circles run clockwise; the outer fills its
    inside and the inner its outside, so the centre is empty.
  - The Λ mark is shape 1331, a polygon.
  - Sprite 1334 places both and is exported `bl1mm_save`.
  - Removed: the external image, its export, the bitmap shape, the "Saving..." label and its font, and the
    frame-counted AS pulse. PLAN_V15 records that the text fallback is dropped.
- **AS:** `save~show~x~y~size~alpha` calls `MinimapSave(show, x, y, size, alpha)`, which attaches once, places,
  scales and sets the alpha.
- **Mod:**
  - **Hiding the native icon:** while the map is docked and shown, `hud.SavingMaterialScale` is set to 0, keeping
    the original (0.5, never a 0 the mod set itself). It is restored when the map hides or undocks, and on
    teardown/disable. Both are logged (`native save icon hidden (scale 0.5 -> 0)` / `restored (0.5)`).
  - **Showing ours:** while a save shows (`SaveDuration > 0`), ours appears at **64 px**, at the native spot moved
    by the ECHO panel's shift. That is the Enhanced echo position + `SAVE_FROM_ECHO` (112.5, 34.45) in p1 space:
    stage ≈ (938.6, 78.0) in 16:9.
  - **Pulse:** each tick, alpha = 100 × clamp(1 − sin(2π · `WorldInfo.RealTimeSeconds`), 0, 1). When ours first
    shows, the mod logs `RealTimeSeconds` next to `SaveStartTime` to confirm the clock matches.
  - `SavingMaterialScale` leaves the save diagnostic's watch list, since the mod now writes it. F7's `save_icon` is
    `{shown, spot, alpha, native_scale}`.

**Tests (red first):**
- AS: attach once; hiding never attaches; placement, scale 50 % for 64 px, alpha.
- Builder: two solid white vector shapes, no bitmaps, no external image or `mmSaveTex` export, the sprite placing
  1330 and 1331, exported `bl1mm_save`.
- Mod:
  - the native icon is hidden while docked and shown, and restored with a log line when the map hides; disable
    gives it back;
  - the spot is (938.6, 77.95), scale 50;
  - alpha is 0, 100, 100 and 29.3 at t = 10.25, 10.75, 10.0 and 10.125;
  - ours hides when the save ends;
  - F7 shows the new field.

Both suites pass on both art variants; 129 unit tests, coverage, ruff and repository checks pass. The offline
Extended UI merge keeps ids 1330, 1331 and 1334 and the export. `release.py --game --enhanced`: the in-mod build
matches (`8eb1e4fd…d042`).

**Built (not installed):** `dist/releases/0.15.2/` in the `feat/save-indicator-diag` worktree holds
`classic_minimap.sdkmod` 0.15.2 `3a75b9f3…ef91` and the profiler 0.1.17 `a8f8f9b8…df9d`.

**Unverified (in game):**
- that the vector logo resembles the game's;
- that the ring's hole renders;
- that `RealTimeSeconds` is the material's clock (pulse in step);
- that `SavingMaterialScale` 0 really hides the native icon;
- the 4:3 spot (the same offset from the echo is assumed).

**Committed** as `c4d452d` on `feat/save-indicator-diag`.

**Installed on the PC (2026-10-28 11:45 UTC, game closed):** `classic_minimap.sdkmod` 0.15.2 `3a75b9f3…ef91` and the
profiler 0.1.17 `a8f8f9b8…df9d`, SHA-256 verified. v0.15.1 (`0d074f7e…4b43`, `f3c9ddb6…ea09`) is backed up in the
main checkout's `dist\v0.15.1-20261028T114521.597685Z\`. The stock `GfxHUD.upk` is unchanged (`5c515c3e…`).

## 3bd. Run 36: v0.15.2 works; the logo looked crude → v0.15.3 redraw (2026-10-28/29)

**Run (PC, Enhanced art, Extended UI, Crimson Lance bunker, 21:33–21:37 UTC; log, a reference logo and a
screenshot provided by the user):** "it works, but it doesn't look entirely accurate… looks much more crude".

**Evidence (log):**
- **Hiding the native icon:** `native save icon hidden (scale 0.5 -> 0)` whenever the map shows docked, and
  `native save icon restored (0.5)` whenever it hides (loading movie, settling, no live pawn).
- **Ours shows and hides with each save:** two saves (21:35:21, 21:37:13) logged `save icon shown at (938.5, 78.0)`
  and `hidden`. The screenshot shows only ours: transparent, left of the map near its top.
- **The clocks match.** `RealTimeSeconds` read 99.658 against `SaveStartTime` 99.610, and 211.675 against 211.627
  (within one tick), so our pulse uses the native material's clock.
- The ECHO reset fix fired once more.

**Shape:** measured from the user's reference (600 px, centre (300, 300)):
- **Ring:** outer radius 270, inner 225.
- **The Λ is an arch:**
  - its outer edge runs from the feet at about (∓170, 140) up to (∓60, −170), then over a rounded top (circle
    centre (0, −145), radius 65, top at −210);
  - its inner edge runs from (∓110, 190) up to (∓32, −130), then over a rounded opening (centre (0, −132.9),
    radius 32.1);
  - the legs widen downward and run into the ring.
- v0.15.2 had a six-point Λ with a sharp apex, short legs ending inside the ring, and a relatively thicker ring
  (60/48).

**Change → v0.15.3 + profiler 0.1.18:**
- **Ring:** 60/50 (the reference's 270/225 scaled), 64 sides.
- **Mark:** `swfbuild.arch_points()` builds the arch as one clockwise outline from `SAVE_ARCH`:
  - the left outer leg, the rounded top (12 segments), the right outer leg;
  - along the ring to the right inner foot;
  - up and back over the rounded opening (12 segments), down the left inner leg, along the ring to the start.
  - The legs are extended to radius 232 (in reference units), so they overlap the ring band with no seam.
- **Preview:** a standard-library rasterizer (scratchpad `logopreview.py`) renders the same geometry next to the
  reference for comparison before a game run.

**Tests (red first):** the AS/builder suite checks:
- the arch's top at −46.7 px (210/270 × 60);
- symmetry;
- the feet ending in the ring band (between radius 50 and 60);
- the ring's outer radius 60;
- an outline with arcs, not six points.

Both suites pass on both art variants; 129 unit tests, coverage, ruff and repository checks pass. The offline
Extended UI merge keeps the ids. `release.py --game --enhanced`: the in-mod build matches (`ce5ab041…912c`).

**Built (not installed):** `dist/releases/0.15.3/` in the `feat/save-indicator-diag` worktree holds
`classic_minimap.sdkmod` 0.15.3 `903a8091…cb04` and the profiler 0.1.18 `c67090fc…7016`.

**Committed** as `d5a4401` on `feat/save-indicator-diag`.

**Installed on the PC (2026-10-29 15:51 UTC, game closed):** `classic_minimap.sdkmod` 0.15.3
`903a8091…cb04` and the profiler 0.1.18 `c67090fc…7016`, SHA-256 verified. v0.15.2 (`3a75b9f3…ef91`,
`a8f8f9b8…df9d`) is backed up in the main checkout's `dist\v0.15.2-20261029T155131.712655Z\`. The stock
`GfxHUD.upk` is unchanged (`5c515c3e…`).

## 3be. Run 37: v0.15.3 looks much better; one shape, the native's proportions, no native icon in the tunnel → v0.15.4 (2026-10-29)

**Run (PC, Enhanced art, Extended UI, Scrap Trap → Crimson Lance HQ, 19:03–19:14 UTC; log and three screenshots
provided by the user):** "looks much better, pulse is good". Three quibbles:
1. Where the arch meets the ring the art looked overlaid, faintly visible in the first screenshot.
2. During a blue tunnel the native icon appeared at its usual spot.
3. The third screenshot is a good one.

Later, comparing ours with the native icon: the native arch is more pointed and does not reach as high.

**Evidence (log):**
- **Four saves showed ours** (`save icon shown at (938.5, 78.0)`), with `RealTimeSeconds` within 0.05 s of
  `SaveStartTime` each time.
- **Two saves came during the tunnel** (19:09:03 and 19:09:30), right after `minimap hidden: loading movie` and
  `native save icon restored (0.5)`, so the native icon drew there; the second load also passed through
  `minimap hidden: HUD off`.

**Causes:**
1. **The overlap.** The ring and the arch were two shapes in one sprite, and the arch's feet ran into the ring band.
   GFx applies the sprite's `_alpha` to each child separately, so during the pulse the overlap was blended twice.
2. **The tunnel.** v0.15.2 hid the native icon only while the map was shown, so every hidden state (tunnel, HUD
   off, settling) gave it back. The HUD movie draws over the tunnel (run 7: the map showed there), so ours can stand in.
3. **The proportions.** The reference logo (run 36) is not the game's icon. Zoomed 4× from the tunnel screenshot,
   in the reference's units (ring radius 270):
   - the ring is the same, 270/225;
   - the arch's outer top is 153 above the centre (ours was 210), rounded with a radius of about 30;
   - the opening's apex is 108 above it, narrowly rounded (radius about 8);
   - the outer legs meet the ring's inner edge near (∓150, 181), the inner ones near (∓82, 218).

**Change → v0.15.4 + profiler 0.1.19:**
- **One shape.** `swfbuild.logo_paths()` builds one shape (`paths_shape`) from three paths:
  - the outer circle (filled inside);
  - a hole around the arch: along the ring's inner edge over the top, then back over the arch;
  - a hole for the arch's opening: up the left leg, over the apex, down, then back along the ring's inner edge.

  The legs end on the ring's inner edge, so nothing is drawn twice. Shape 1331 is gone, and the sprite places only
  1330.
- **The native's proportions.** `SAVE_ARCH` now holds each edge's foot and its top circle (`outer`: centre
  (0, −123), radius 30; `inner`: centre (0, −100), radius 8). The legs run tangent to those circles.
- **Native icon hidden whenever ours can stand in.** `update_save_icon` keeps `SavingMaterialScale` at 0 while the
  mod has a save spot (docked), whether or not the map shows. It is restored when the mod is idle and on disable.
  Ours shows during every save.

**Tests (red first):**
- **AS suite:**
  - it decodes the logo's paths from the built movie: one placed shape with three paths;
  - the outer circle has radius 60, and the holes stay inside radius 50;
  - both holes are symmetric;
  - the hole around the arch reaches the ring at the top;
  - the arch's top is at −34 px, and the opening's apex at −24 px, narrow.
- **Mod suite:** during the tunnel and with the HUD off, the map hides, but ours stays visible and the native
  stays at 0. Nothing is restored.

Both suites pass on both art variants; 129 unit tests, coverage, ruff and repository checks pass.
`release.py --game --enhanced --profiler`: the in-mod build matches (`551c4b30…f43f`). A preview from the standard
library rasterizer matches the zoomed native icon.

**Built (not installed):** `dist/releases/0.15.4/` in the `feat/save-indicator-diag` worktree holds
`classic_minimap.sdkmod` 0.15.4 `a355b946…96a0` and the profiler 0.1.19 `41fec364…6b74`.

**Committed** as `cf622ec` on `feat/save-indicator-diag`.

**Installed on the PC (2026-10-30 01:02 UTC, game closed):** `classic_minimap.sdkmod` 0.15.4
`a355b946…96a0` and the profiler 0.1.19 `41fec364…6b74`, SHA-256 verified. v0.15.3 (`903a8091…cb04`,
`c67090fc…7016`) is backed up in the main checkout's `dist\v0.15.3-20261030T010236.901635Z\`. The stock
`GfxHUD.upk` is unchanged (`5c515c3e…`).

**Unverified:**
- whether our icon draws over the tunnel itself (run 7 suggests so) and with the HUD off;
- the new proportions in game;
- the 4:3 spot.

## 3bf. Run 38: v0.15.4 looks good (2026-10-30)

**Run (PC, Enhanced art, Extended UI, Crimson Lance HQ, 01:04–01:13 UTC; log and a screenshot provided by the
user):** "looks good". The screenshot shows our logo left of the map with the lower, pointed arch.

**Evidence (log):**
- **The native icon stayed hidden from the first HUD.** `native save icon hidden (scale 0.5 -> 0)` came at
  01:06:11, while the map was still hidden (`HUD off`), and was never restored during the session.
- **Four saves showed ours** at (938.5, 78.0), each with `RealTimeSeconds` within 0.07 s of `SaveStartTime`.
- **A save into the tunnel stayed ours.** The save at 01:13:06 was followed 0.5 s later by
  `minimap hidden: loading movie`. Our icon stayed shown through the tunnel and hid when the save ended (01:13:11),
  with no native restore.
- The ECHO reset fix fired nine times; Angel's scope particle was logged as before.

**Result:** the run 37 quibbles are resolved: one shape (no doubled overlap reported), the native's proportions,
and no native icon in the tunnel.

**Two follow-up questions from the user:**
- **"Does it need to sit that far away from the minimap?"** No. Its ring ended about 85 stage px left of the map's
  frame only because v0.15.2 kept the native icon's offset from the ECHO panel. The user chose to align it closer.
- **"Did we impact the checkmarks for the objectives?"** No. The save work doesn't touch `check1..5`. Zoomed from the
  run 37 and 38 screenshots, the boxes draw with their ticks (two ticked, one empty in run 37; three empty in
  run 38), and the notched corner looks like the game's own box art.

**Change → v0.15.5 + profiler 0.1.20:** `save_spot()` now places ours beside the docked map's frame:
- It takes the map's stage matrix (`dock_matrix`, so Docked size and the HUD layout count) at the frame's top-left
  corner, which is the window less `BOX_MARGIN` 5.
- The ring (radius 30 at 64 px, `SAVE_RING`) ends `SAVE_GAP` 8 px left of that corner, with its top level with the
  frame's.
- At the 16:9 layout that puts the centre at stage (1021.5, 64.2), where it was (938.5, 78.0). `SAVE_FROM_ECHO` is
  gone.

**Tests (red first):** the mod suite works the example through from the docked matrix: the centre lands at
(1021.45, 64.20), and F7 reports the spot as (1021.5, 64.2). Both suites pass on both art variants; 129 unit tests,
coverage, ruff and repository checks pass. `release.py --game --enhanced --profiler`: the in-mod build matches
(`657d3b16…4605`).

**Built (not installed):** `dist/releases/0.15.5/` in the `feat/save-indicator-diag` worktree holds
`classic_minimap.sdkmod` 0.15.5 `97a91818…cdc3` and the profiler 0.1.20 `f7bdd932…0e9d`.

**Committed** as `b54ff98` on `feat/save-indicator-diag`.

**Installed on the PC (2026-10-30 01:22 UTC, game closed):** `classic_minimap.sdkmod` 0.15.5
`97a91818…cdc3` and the profiler 0.1.20 `f7bdd932…0e9d`, SHA-256 verified. v0.15.4 (`a355b946…96a0`,
`41fec364…6b74`) is backed up in the main checkout's `dist\v0.15.4-20261030T012212.165175Z\`. The stock
`GfxHUD.upk` is unchanged (`5c515c3e…`).

**Unverified:** the new spot in game (16:9 and 4:3).

## 3bg. v0.15.6: our save icon as big as the native one (2026-10-30, offline only)

**Question (user):** "is it also scaled the same as the native icon?" No. Measured on the run 37/38 screenshots
(2000 × 1125, so 1.5625 screen px per stage px):

| Icon | Ring across (screen px) | Stage px |
|---|---|---|
| Native (tunnel, run 37) | ≈ 99.5 | ≈ 63.7 |
| Ours at 64 px (runs 37, 38) | ≈ 93.5 | 60 |

Ours measures as built: the ring has radius 60 in its 128 px art box. The native texture's ring fills nearly its
whole box, so at the same 64 px ours was about 6% smaller. At this 16:9 resolution, the native icon and the HUD
movie scale by the same factor (64 × 1.5625 ≈ 100).

**Change → v0.15.6 + profiler 0.1.21 (the user's choice):**
- `SAVE_SIZE` is now 68: the ring is 63.75 stage px across, about 99.6 screen px here.
- `SAVE_RING` is now written as 60/128. The spot follows the ring's size, so the 8 px gap and the level tops hold:
  centre (1019.6, 66.1).

**Run 39 (PC, v0.15.5, 2026-10-30; a screenshot and the log provided by the user):** the native icon was turned back
on from the console (`set WillowHUD SavingMaterialScale 0.5`) to compare the two side by side.
- **Size:** the native ring is ≈ 99 px tall and ours (64 px) ≈ 93, the same gap as measured before; the 68 px
  change covers it.
- **Gap:** at 8 px, ours sat against the map's north marker ("N"), which runs around the frame's edge. The user
  suggested 16 px.
- **Arch:** the user saw a slightly wider arch on the native icon. Across both icons in that screenshot, the
  native's outer edge sits at −0.15, −0.23, −0.31, −0.39, −0.45 and −0.54 (x per ring radius) at heights −0.4 to
  0.6. Ours sat about 0.01–0.02 inside that, so the native arch is about 1–2 px wider in total. The opening and the
  feet matched within the measurement.

**More changes in v0.15.6 (not yet installed then):**
- `SAVE_GAP` is now 16, putting the centre at (1011.6, 66.1).
- `SAVE_ARCH['outer']`: top radius 36 (was 30), foot (−153, 181) (was −150), with the top still 153 above the centre.
  Fitted with a scratch script, every measured height is within 0.013 of the native.

**Tests (red first):**
- **Mod suite:** it expects scale 53.125% and the centre at (1011.575, 66.075), worked from the docked matrix.
- **AS suite:** it checks the arch's outer edge against the native measurements at the six heights (±0.015).

Both suites pass on both art variants; 129 unit tests, coverage, ruff and repository checks pass.
`release.py --game --enhanced --profiler`: the in-mod build matches (`a82f03c1…53aa`).

**Built (not installed):** `dist/releases/0.15.6/` in the `feat/save-indicator-diag` worktree holds
`classic_minimap.sdkmod` 0.15.6 `2c8229be…51bc` and the profiler 0.1.21 `e18dc1bf…73f0`.

**Committed** as `9b521ee` on `feat/save-indicator-diag`.

**Installed on the PC (2026-10-30 02:01 UTC, game closed):** `classic_minimap.sdkmod` 0.15.6
`2c8229be…51bc` and the profiler 0.1.21 `e18dc1bf…73f0`, SHA-256 verified. v0.15.5 (`97a91818…cdc3`,
`f7bdd932…0e9d`) is backed up in the main checkout's `dist\v0.15.5-20261030T020140.697518Z\`. The stock
`GfxHUD.upk` is unchanged (`5c515c3e…`).

**Unverified:**
- the size and spot in game;
- whether the native icon scales like the HUD movie at other aspect ratios (the Deck's 16:10, 4:3), since it is
  drawn on the canvas.

## 3bh. Run 40: v0.15.6 "much better"; rounded joins, wider opening, thinner ring → v0.15.7 (2026-10-30)

**Run (PC, v0.15.6, native turned back on from the console; a screenshot provided by the user):** "much better".
Two remaining differences:
1. Where the arch meets the ring, the native's corners are rounded and ours are sharp.
2. The arch's inner edge is still slightly narrower, so the base of the legs looks wider.

**Evidence (zoomed screenshot and the run 39 measurements):**
- **Joins:** the native's legs meet the ring in fillets, outside the arch and inside its opening.
- **Opening:** native's inner edge sits at 0.15, 0.19, 0.25, 0.31 (x / radius) at heights 0–0.6. Our own icon
  measured about 0.019 wide of its model at the same heights, so the native's corrected edge is 0.131, 0.171,
  0.231, 0.291. Our model gave 0.116, 0.163, 0.209, 0.256, so the opening was narrower lower down.
- **Ring:** the native's inner ring edge sits at ~0.87 of the radius at three separate heights, against ours at
  0.833 (our measurement was within 0.01 of the model). The native ring is thinner, and its legs reach further down.

**Change → v0.15.7 + profiler 0.1.22:**
- **Ring:** 60/52 (was 60/50).
- **Inner edge:** foot (−92, 218) (was −82), apex circle centre (0, −102) radius 8 (apex at −110, was −108).
  It is within about 0.01 of the corrected native edge at every height.
- **Fillets:** `logo_paths()` rounds each leg's join with the ring's inner edge (`SAVE_FILLETS` outer 16, inner
  18, in reference units; 8 segments).
  - The fillet's centre lies the fillet radius off the leg and inside the ring, and its arc runs from the leg's
    tangent point to the ring's.
  - The holes' outlines are now smooth.
  - An outer fillet of 22 closed the hole above 0.6 of the radius, and 18 bent the edge past the native's
    there; the tests caught both.
- **A slip along the way:** the opening's path first dropped its last point on the left leg, which made it
  asymmetric. The symmetry assertion caught it.

**Tests (red first):**
- **AS suite:**
  - the opening's inner edge matches the corrected native at four heights (±0.015);
  - no vertex of either hole turns by more than 20°, skipping vertices between segments under 0.5 px, where
    rounding to twips bends the 2 px apex;
  - the holes stay inside radius 52, and the outer hole reaches the ring's inner edge at the top.
- Both suites pass on both art variants; 129 unit tests, coverage, ruff and repository checks pass.
- `release.py --game --enhanced --profiler`: the in-mod build matches (`ad5d5a3a…9763`).

**Built (not installed):** `dist/releases/0.15.7/` in the `feat/save-indicator-diag` worktree holds
`classic_minimap.sdkmod` 0.15.7 `ac81f5c9…0848` and the profiler 0.1.22 `1e54a601…a556`.

**Committed** as `35e6e7d` on `feat/save-indicator-diag`.

**Installed on the PC (2026-10-30 02:34 UTC, game closed):** `classic_minimap.sdkmod` 0.15.7
`ac81f5c9…0848` and the profiler 0.1.22 `1e54a601…a556`, SHA-256 verified. v0.15.6 (`2c8229be…51bc`,
`e18dc1bf…73f0`) is backed up in the main checkout's `dist\v0.15.6-20261030T023412.707147Z\`. The stock
`GfxHUD.upk` is unchanged (`5c515c3e…`).

**Unverified:** the new joins, opening and ring side by side with the native in game.

## 3bi. Run 41: v0.15.7 looks good; the save icon is done at 16:9 (2026-10-30)

**Run (PC, Enhanced art, Extended UI, Crimson Lance HQ area, 20:50–21:10 UTC; log and two screenshots provided by the
user, with the native icon turned on from the console):** "looks good". The two icons match at full and low pulse.

**Evidence (log):**
- Three saves showed ours at (1011.5, 66.1), each within 0.04 s of `SaveStartTime`.
- The native stayed hidden from the first HUD until the console turned it on.
- No ECHO reset happened in this run.

**Two things F7 showed:**
- **`hud_fixes` read `inf`.** `mmHudFixes` stays undefined until the first reset, so F7's read of it is meaningless
  in a run with none. Cosmetic; the logging path already guards with `finite()`.
- **The 108% zoom floor again, with a cause.** `zoom_fit` held the pawn and a point about 57,600 units away
  (`raw` 30.1, fitted 108). A far objective drives the fit to the floor, which is the open "zoom without a nearby
  objective" item. Enhanced's behaviour for such a slot is still to compare.

**Unverified:** 4:3, and how the native icon scales at 16:10 (Deck).

## 3bj. v0.16.0: the options menu and the research code cleaned up for 1.0 (2026-10-30, offline only)

**Why:** after run 41 the user asked what is left for 1.0 and for a pass over the options, then approved the proposal.
The Angel and autosave research was finished but still ran: its hooks and watches filled the log (each new screen
particle, a sniper scope included, wrote thousands of characters).

**Options menu:**
- **Groups** (`GroupedOption`, shown inline): Map, Markers, HUD.
- **Sub-menus** (`NestedOption`): Custom position, Advanced.
- **"Rotation offset" removed:** it was hidden and always 0. It also left the movie: `tick~u~v~deg~rotate`,
  `recenter~rotate` and `MinimapRecenter(rotate)`.
- **Names:** "Zoom (vs Enhanced)" is now "Zoom". The F8 keybind "Rebuild minimap" is now "Refresh map markers",
  matching its button.
- **American spelling:** in the option descriptions and the README.
- **Saved settings:** `mods_base` nests a group's values under its name in `classic_minimap.json`, so values saved
  before v0.16.0 go back to their defaults once. "Enhanced folder" stays at the top level, as the README says.
  `mods_base` associates group children with the mod recursively, so saving and the on-change callbacks work as
  before (read from the installed `mods_base`; not yet seen in game).

**Code removed (about 370 lines):**
- the screen-mesh, root `vog` clip and screen-particle watches and dumps;
- the hooks on `PlayVoGEchoCall`, `Behavior_PlayEchoCall`, `ClientPlayEchoCall`, `PlayEchoCall`,
  `SetUpVoGScreenParticle` and `ShowScreenParticle` POST;
- the `NotifySavingStarted`/`Complete` hooks, which never fired;
- the save-state watch and the "save icon shown/hidden" lines;
- the F7 fields `angel`, `vog`, `screen_particles` and `save_indicator`.

Kept: the PRE `ShowScreenParticle` hook that places Angel's video, the save icon, F7's `save_icon`, and the
"moved it again" line for ECHO resets.

**Other cleanup:**
- **`hud_fixes`:** F7 reports the mod's own count, 0 before any reset, instead of reading an undefined movie
  variable (`inf`, run 41).
- **`sdk_mods/minimap_probe` removed** from the repository. The installed `minimap_probe.sdkmod` on the PC is
  untouched.
- **README:** the status line, the grouped options tables, and a line about the save icon.

**Tests (red first):**
- **Mod suite:**
  - the menu's exact structure, each option once;
  - the keybind names, and no "centre" or "colour" in descriptions;
  - the removed hooks and F7 fields are absent, and a save logs nothing;
  - `'hud_fixes': 0` before any reset;
  - the stub gained `GroupedOption`/`NestedOption`.
- **AS suite:** the tick and recenter commands without the offset; rotation is now minus the heading.
- Both suites pass on both art variants; 129 unit tests, coverage (floors unchanged), ruff and repository checks
  pass. `release.py --game --enhanced --profiler`: the in-mod build matches (`eb36814b…4db2`).

**Built (not installed):** `dist/releases/0.16.0/` in the `feat/save-indicator-diag` worktree holds
`classic_minimap.sdkmod` 0.16.0 `90599fdb…dc21` and the profiler 0.1.23 `6c1fe8cb…cce8`.

**Committed** as `8b725ab` on `feat/save-indicator-diag`.

**Installed on the PC (2026-10-30 21:26 UTC, game closed):** `classic_minimap.sdkmod` 0.16.0
`90599fdb…dc21` and the profiler 0.1.23 `6c1fe8cb…cce8`, SHA-256 verified. v0.15.7 (`ac81f5c9…0848`,
`1e54a601…a556`) is backed up in the main checkout's `dist\v0.15.7-20261030T212656.013372Z\`. The stock
`GfxHUD.upk` is unchanged (`5c515c3e…`).

**Unverified in game:** the groups and sub-menus in the SDK's menu, Angel still centered, rotation, the save icon.

## 3bk. The release workflow runs CI first (2026-11-02, offline only)

**Why:** `release.yml` only checked the version fields, Python syntax and the archive, so it could publish a build
that fails CI, from any branch. The user asked to tighten it before the first push.

**Change (no mod version change):**
- `ci.yml` also runs through `workflow_call`, so a release uses the same checks.
- `release.yml` has three jobs: `main-only` refuses any other branch or tag, `checks` runs `ci.yml`, and `release`
  (publishing) needs `checks`.
- `quality_checks.py repository` calls a new `release_gate_errors()`, which fails if that order is removed. It reads
  the jobs line by line, because the CI tools have no YAML parser.
- `docs/CI.md`: the release flow, plus stale notes (the test count, the removed probe, the mod's mutation score).

**Tests (red first):** `test_quality.py` checks a passing sample, each way of removing the gate, and the real
workflows, which failed all four rules before the change. 131 unit tests, coverage, ruff and repository checks pass.

**Unverified:** the workflow syntax (no actionlint, Docker or YAML parser here; the hosted lint job runs actionlint),
and the release path itself until the pre-release.

## 3bl. Fewer billable CI minutes (2026-11-02, offline only)

**Why:** the repository is private, with 2,000 Actions minutes a month, and earlier concurrent runs used them all.

**Cause:** no single test stood out. The slowest cases take 5–8 s and do real work (release builds, installs, a real
hang being killed). The cost was one process per case: about 0.5 s each under coverage, on top of the test itself.
Run as one process each, the suites took 0.3–1.6 s (fast suites), 11 s (`test_runners`), 27 s (`test_workflow`) and
29 s (`test_land`).

**Change (no mod version change):**
- `run_tests.py`: the default run uses one process per suite. `test_ci.SourceChecks` stays per case because its cases
  run the real mod's `main()`, which fails on a second run in one process. Explicit test IDs stay per case.
- `ci.yml`: pushes that change only `docs/` or a root `.md` file skip CI, except the two docs `bump_version.py` edits,
  which the tests read. The filter is on `push` only, because GitHub leaves required checks pending on a path-filtered
  PR workflow. `quality_checks.py repository` calls a new `ci_trigger_errors()` that enforces both rules.
- `docs/CI.md`: billable-minute notes and the new process model.

**Tests (red first):** four new cases in `test_quality.py` and `test_runners.py`. 135 unit tests, the coverage gate,
ruff and repository checks pass.

| Run (Windows, i7-6700K) | Processes | 2 workers | Automatic (8) |
|---|---:|---:|---:|
| Before | 135 (131 when timed) | about 90 s | about 45 s |
| After | 14 | 50 s | 36 s |

Coverage is identical per gated file between a grouped run and a per-case run of the same tests.

**Unverified:** the Linux jobs and Python 3.11 under grouping (suites sharing a process could behave differently
there), the path filter on a real push, and the hosted minutes saved, until the first hosted run. `land_branch` and
`test_workflow` fixtures were not changed.

## 3bm. First hosted CI run: Windows checked out the fixtures with CRLF (2026-11-02, offline only)

**What happened:** the first hosted run of `7724aa8` failed on Windows/Python 3.11:
`test_profiler.FixtureChecks.test_regenerated_fixtures_match_committed_bytes` found `invalid-bucket-sum.json` with
CRLF line endings. Ubuntu/Python 3.13 passed every suite shown in the log the user pasted (the log ended before
`test_runners` and the coverage combine).

**Cause:** Windows runners set `core.autocrlf=true`, so Git converted the LF fixtures to CRLF on checkout. Local
checkouts don't, which is why it never failed here. Grouping (§3bl) was not involved.

**Fix:** `.gitattributes` checks out every text file with LF (`* text=auto eol=lf`); the index was already all LF,
so no file changed. `quality_checks.py repository` calls a new `line_ending_errors()`, which fails unless every
tracked fixture has `eol=lf`.

**Tests (red first):** `test_quality.py` failed on the real repository before the attribute was added. A clone made
with `core.autocrlf=true` passes the whole default run.

The user later reported that the Ubuntu/3.13 job was cancelled before its coverage step.

## 3bn. CI tests the game's Python: Windows/3.14 and Ubuntu/3.13 (2026-11-02, offline only)

**Why:** CI tested Python 3.11 (the tools' stated minimum) on two of its three jobs, but nothing runs on 3.11. The
PythonSDK in the user's install embeds Python 3.14 (`Binaries\Plugins\python314.dll`), which CI never tested, and the
local tools run on 3.13.

**Change:** the test matrix is two jobs: Windows/Python 3.14 (the game's OS and interpreter) and Ubuntu/Python 3.13
(the tools' Python and POSIX process groups for the mutation runner). Lint and mutation testing move from 3.11 to
3.13; ruff targets `py313`; TOOLS.md states 3.13+. One fewer Linux job per run.

**Tests:** configuration only. Ruff, repository checks, 136 unit tests and the coverage gate pass on Python 3.13.

**Unverified:** Python 3.14 is not installed here, so the Windows/3.14 job (and the pinned ruff, coverage and Cosmic
Ray on it) is first tested by the hosted run.

## 3bo. v0.16.1: a faster Extended UI merge, and its timing split by phase (2026-11-25, offline only)

**Why:** with Extended UI the merge was the one visible hitch: 3.0–3.4 s on the PC and 3.3–4.4 s on the Deck, once
per session (§3ai, §3ap, §3aw). The user chose to start with the timing breakdown and the bit reader.

**Evidence (offline, against the installed `Mods/Custom UI/GfxHUD_MOD.upk`, 666,106-byte movie, and the player-built
movie cache):** the merge took 1.07 s in CPython 3.13 on the PC. cProfile put almost all of it in the shape walker's
bit reader: 977,411 calls to `Bits.u`, one per bit, to count the gradient fills in Extended UI's 408 shapes. Reading
the same movie from its package on disk took 0.06 s, against about 0.7 s for `bytes(RawData)` in game (run 18). The
in-game total is about 1 s more than run 18's parts add up to, and the log gave only the total.

**Change → core v0.16.1, profiler 0.1.24 (its supported list):**
- The log line splits the merge: `merged in T.TTs (read R.RRs, merge M.MMs, write W.WWs; N bytes)`. The write
  includes constructing the `GFxMovieInfo`.
- `swfmerge.Bits.u` reads a whole field with one `int.from_bytes` and still raises `IndexError` past the end, so a
  truncated shape is still refused. `walk_shape` reads each record's 6-bit header in one call and skips the
  coordinate fields it never needed (`Bits.skip`).

**Result:** the merge into Extended UI's movie went from 1.07 s to 0.19 s (best of 3), about 5.7 times faster. The
merged bytes are identical for both art variants, every shape in six real movies (Extended UI, stock classic HUD,
Enhanced HUD, status menu and both of our movies) walks to the same bitmaps and gradients, and both rebuilt movies are
byte for byte the same as before.

**Tests:** the mod suite's merge scenario now requires the phase times in the log line (it failed first). Two new
`test_swfmerge` cases pin the reader: fields of many widths from any bit offset, and the error past the end (they pass
on both readers; this part is a refactor). Both suites on both art variants, 138 unit tests, the coverage floors
(swfmerge 98.93% line / 95.69% branch), ruff and repository checks pass. `release.py --game --enhanced --profiler`:
the in-mod build matches (`6dc743b6…4708`). Bundle in the worktree's `dist/releases/0.16.1/`:
`classic_minimap.sdkmod` `e0312eec…a01e`, `classic_minimap_profiler.sdkmod` `38807f92…7693`.

**Installed on the PC (2026-11-26 00:33 UTC, game closed):** both files through `install.py --profiler`, SHA-256
verified. v0.16.0 `90599fdb…dc21` and profiler 0.1.23 `6c1fe8cb…cce8` are backed up in the main checkout's
`dist\v0.16.0-20261126T003305.719998Z\`. v0.16.0 was never played, so this is also its first in-game check (§3bj).

**Unverified:** the in-game times. The new log line will show where the unexplained second goes. Still open from the
plan: reading the foreign movie from its package instead of `RawData` (about 0.65 s), and caching the merged movie
on disk.

## 3bp. CI's Ubuntu unit-test step hung in `test_runners` (2026-11-25, offline only)

**What happened:** the Ubuntu/Python 3.13 job's step `run_tests.py --coverage` (2 workers, 14 processes) was cancelled
at the 10-minute job timeout. 13 processes printed PASS; `test_runners.RunnerChecks` never reported. The first hosted
run's Ubuntu log (§3bm) also ended before `test_runners`, so it has never finished on Linux.

**Cause:**
- `test_mutation_command_kills_a_hanging_suite_and_its_children` gives `test_mutants.main` a suite whose grandchild
  loops forever, with a 3 s budget. At the budget, `test_mutants.kill_tree` kills the tree with `taskkill /T` on
  Windows, but only with `proc.kill()` on POSIX: the direct child dies and the looping grandchild is orphaned.
- The orphan inherits the stdout/stderr pipes of the `run_tests.py --case test_runners.RunnerChecks` process.
  `run_case`'s `subprocess.run(capture_output=True)` waits for EOF on them, which never comes. So even after the test
  process ends, the runner waits until CI cancels the job, with no output, while the orphan spins one of the two
  cores.
- The same gap would hit a real POSIX mutation run whose mutant hangs in a grandchild.
- Windows kills the whole tree, so the suite passed locally.

**Fix (no mod version change):**
- `test_mutants.kill_tree` on POSIX snapshots the process tree from `ps -A -o pid=,ppid=` (new
  `process_tree(root, table)`) and SIGKILLs every PID in it. Snapshotting first means killed parents can't hide
  their children.
- `run_tests.py` gives each test process a timeout, `--timeout`, default `DEFAULT_TIMEOUT` = 240 s. The slowest
  suite takes about 35 s locally. A hung process then fails with its output and "timed out after N s" instead of
  the job being cancelled silently. On POSIX, `subprocess.run` only waits for the killed child after a timeout, not
  for its pipes, so an orphan can't stall it.
- The grandchild test now kills any grandchild it leaves behind (`addCleanup`), so a regression fails instead of
  hanging the run.

**Tests (red first):**
- `test_posix_tree_kill_covers_every_descendant`: the tree walk, platform-independent. It failed with no
  `process_tree`.
- `test_a_hanging_case_fails_at_the_timeout_instead_of_stalling_the_run`: a `HangingExample` with `--timeout 3`
  must fail with the message within 30 s. It failed with no `DEFAULT_TIMEOUT`.

138 unit tests pass. The coverage gate, ruff and repository checks pass. Both real-movie suites pass on both art
variants.

**Timings** (`run_tests.py`'s default jobs, 2 workers, coverage, Windows i7-6700K):

| | Total | `test_land` | `test_workflow` | `test_runners` |
|---|---:|---:|---:|---:|
| Before | 54.3 s (Ubuntu CI: hung, cancelled at 10 min) | 35.5 s | 33.0 s | 16.5 s |
| After | 55.0 s | 32.8 s | 31.9 s | 18.4 s |

`test_runners` gains about 2 s from the new 3 s timeout case.

**Unverified:** the POSIX kill path, until the next hosted Ubuntu run. No Linux is available locally (no WSL
distribution or Docker).

## 3bq. Run 42: v0.16.1 on the PC with Extended UI; the merge takes 1.39 s (2026-11-26)

**What was played:** v0.16.1 and profiler 0.1.24 (§3bo) with Extended UI 1.3.2 and Mission Selector 1.1.1, Enhanced
art. Arid Hills, the DLC3 hub (`dlcmap1`), Dry, Arid again and `interlude1`; one 60 s profiler capture from 01:21:10
to 01:22:10 UTC covering two level changes. Evidence: the user's `unrealsdk.log` and the capture's report
(`917cedfb…`), both read from the game folder. No errors or refusals from either mod.

**Merge (first main menu, 01:18:53):** `merged in 1.39s (read 0.77s, merge 0.28s, write 0.35s; 843049 bytes)`.
Before v0.16.1 the same merge took 3.0–3.4 s on the PC (§3ai, §3ap); the parts now add up to the total, so there is
no unexplained second. The Python merge is 0.28 s in game against 0.19 s offline (the SDK's Python 3.14 against 3.13
here). Reading `RawData` is now over half the total: reading the movie from its package on disk (0.06 s offline) is
the next step, then caching the merged bytes to drop the 0.28 s.

**Movie build (01:16:46, a cache miss because the version changed):** 0.71 s with Enhanced art, against 1.95–3.60 s
on the PC before (§3al, §3aq). The builder counts gradients with the same shape walker, so it got faster too.

**Profiler capture (core 0.16.1; the nearest earlier report is core 0.10.0 in Arid, 2026-10-25, so this is a
rough comparison only):**

| Metric | 0.10.0 | 0.16.1 |
|---|---:|---:|
| Admitted ticks: count, mean | 872, 2.19 ms | 892, 1.39 ms |
| Slowest tick | 25.6 ms | 12.7 ms |
| `objective_key` mean | 2.31 ms | 1.20 ms |
| `threat_string` mean | 0.58 ms | 0.20 ms |
| `hidden_reason` mean | 0.47 ms | 0.26 ms |
| `rebuild_in_place` | not observed | 4, max 9.9 ms |

Admitted p95 is ≤ 5 ms in both (bucket upper bound). The capture saw the per-frame metrics, two captures, four
rebuilds and the `cmd` ops; only `start` and `cmd.frame` were unobserved (`metric_unobserved`). So the v0.16.0 cleanup
didn't cost the profiler any coverage (§3bj).

**Level changes (loading movie → map ready → shown):** DLC3 hub 5.3 s + 3.5 s; Dry 4.0 s + 3.6 s; Arid 6.6 s + 3.0
s; `interlude1` 6.2 s + 3.5 s. That's 7.6–9.7 s in all, much as in run 19: the anchor wait, then the 3 s settle rule.
This is still a tuning item.

**Also seen:** the game put the ECHO panel back 17 times, and the mod moved it each time. The native save icon was
hidden (scale 0.5 → 0).

**Options menu (user, same session):** the grouped options are fine, so v0.16.0's menu is confirmed (§3bj).

**Unverified:** the Deck on v0.16.1.
