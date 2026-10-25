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
- **Gates:** 129 unit tests, both real-movie suites on both variants, and the gates pass. Not installed or played.
