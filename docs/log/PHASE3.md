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

At the user's request, AGENTS now starts new coding tasks in a new worktree on a codex/<task> branch, preserves other tasks' checkouts, reuses the task's own worktree for continuations, and accounts for ignored local game/build inputs. Explicit instructions to work directly on main override the default; the user requested that exception for this commit. Added ignore rules for local worktree and assistant-state directories, leaving the existing enhanced-minimap-box worktree untouched.

The commit includes the pending release workflow, CI and quality-gate setup from §3p–3q. The user has since configured origin as https://github.com/dacharl/bl1-classic-minimap.git. No runtime or installed files changed; installed hashes and pending in-game checks remain those in §3n. Validation remains the passing suites, lint/workflow checks, coverage floors and 2,806-mutant baseline recorded in §3q; staged content/whitespace and commit identity/message are checked before pushing. Hosted CI verification follows the push.

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
