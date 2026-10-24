# BL1 Enhanced minimap: how it works, and how to bring it to BL1 GOTY (classic)

## Targets

| | Classic | Enhanced |
|---|---|---|
| Exe | `Borderlands/Binaries/Borderlands.exe` (x86, v1.5.0.0) | `BorderlandsGOTYEnhanced/Binaries/Win64/BorderlandsGOTY.exe` (x64, v1.5.0.0) |
| SHA-256 (REA `open_binary`) | `71b58c40…dc42a` | `57c5dc7b…ef56` |
| Package version | 584 / licensee 58 | 594 / licensee 58 |
| `WillowGame.u` | LZO-compressed (11 chunks) | LZO-compressed (37 chunks) |
| `GfxHUD.upk` | raw, HUD movie 442 KB | raw, HUD movie 739 KB |

### Evidence limits (read this first)

- **Both executables are SteamStub-wrapped.** Each has a `.bind` section and a `.text` section with entropy 8.00, so the code is encrypted on disk. Native function *bodies* can't be disassembled statically. What I could read is the unencrypted `.rdata`/`.data`: the native exec registration tables (name → address) and the string literals the natives use.
- **REA has no deep-native engine on this machine.** Ghidra isn't installed, and IDA and Kuna aren't configured. REA opened both binaries and recorded their identities, but `search_strings` and the disassembly tools returned `provider_unavailable`. Native evidence below comes from my own pefile/capstone tooling over the unencrypted sections.
- **UnrealScript and ActionScript are fully readable.** I decompressed the packages and disassembled both. This is where most of the behaviour lives.

Everything below is labelled **Observed** (read directly from bytes), **Inferred**, or **Unknown**.

---

## 1. How the Enhanced minimap works

### 1.1 Architecture

```
ActionScript (GfxHUD.upk, HUD movie)            UnrealScript (WillowGame.u)              Native (BorderlandsGOTY.exe, encrypted)
------------------------------------            -----------------------------            --------------------------------------
p1..p4 per-player HUD clips                      WillowHUDGFxMovie                        UWillowHUDGFxMovie::execUpdateMinimap @141328f90
  └ "map"  = minimap_frame (class Minimap)  ◄──   .extInitMinimap()  ◄── ExternalInterface   (called from native HUD tick; no script caller)
       ├ maps (zone art, per-level frames)        .extInitComplete() ◄── ExternalInterface   UWillowGFxHelperMap natives (shared with full map)
       │   ├ themap / landmarks / players / enemy  .UpdateCompassMinimapVisibility()          UWillowGFxHelperMinimap::execUpdateThreats @140b427d0
       ├ northMC, customWaypointMC,               .RebuildMinimapObjects()  (bRebuildMinimapObjects flag)
       └ currentObjectiveMC                     WillowGFxHelperMinimap extends WillowGFxHelperMap (bIsMinimap=true)
root AddLandmark/UpdateLandmark/... fan out to   WillowPlayerController.MarkMinimapDirty / SetMinimapShouldRotateFromProfile
p<N>.map.<fn>                                    WillowProfileSettings: WPS_ShowMinimap, WPS_MinimapShouldRotate
```

**The main point:** the Enhanced minimap is not a new map system. It is the **existing full-screen map helper (`WillowGFxHelperMap`) pointed at the HUD movie**, with a `bIsMinimap` flag. The changes are:
- a subclass that adds a few natives;
- a new Flash clip class (`Minimap`) that recentres, rotates and clamps edge icons;
- a native per-frame update.

### 1.2 Script-side evidence (Observed)

From [evidence/out_E_minimaphelper.txt](evidence/out_E_minimaphelper.txt), [evidence/out_E_hudmovie.txt](evidence/out_E_hudmovie.txt) and [evidence/out_E_map.txt](evidence/out_E_map.txt):

- **`WillowGFxHelperMinimap.Init`** sets `bIsMinimap = true`, then calls `WillowGFxHelperMap.Init(InPlayerOwner)`. The parent class is `WillowGFxHelperMap`.
- **`WillowHUDGFxMovie.extInitMinimap`** is called from Flash via ExternalInterface 15 times in the HUD movie:
  ```
  MapHelper = new WillowGFxHelperMinimap
  AS_ClearLandmarks()
  MapHelper.SetHUDMovie(self)
  MapHelper.Init(WillowPlayerController(PlayerOwner))
  MapHelper.ResetMapObjects()
  MapHelper.InitMapFrame(self)
  ```
- **`WillowHUDGFxMovie.extInitComplete`** is called from each zone frame of the `maps` clip once the art is on stage:
  ```
  MapHelper.InitMapFrameVars(self); MapHelper.UpdateObjects(true)
  MapHelper.CurrentScaleIdx = 3; MapHelper.ApplyScale(self)
  MapHelper.QuickAccessInit(); MapHelper.AnalogScale(self, 1.0)
  MapHelper.ApplyFlash(self); UpdateCompassMinimapVisibility()
  ```
- **`UpdateCompassMinimapVisibility`** loops over split-screen players and reads profile settings:
  - `ShowCompass` → sets `p<N>.bearing._visible`;
  - `ShowMinimap` → sets `p<N>.map._visible`, then calls `AS_UpdateEchoPosition` (moves the ECHO panel out of the minimap's way);
  - `MinimapShouldRotate` → calls `MapHelper.SetMinimapShouldRotate(I, value)`.
- **`UpdateMinimap(int PlayerNum)`** is a native with no UnrealScript caller.
- **Dirty-flag rebuild:**
  - `AddInteractiveObject` sets `bRebuildMinimapObjects = true`.
  - The event `RebuildMinimapObjects()` calls `ClearMapObjects()`, `AS_ClearLandmarks()` and `BuildMapObjects()`.
  - `WillowPlayerController.MarkMinimapDirty()` sets the same flag through `myHUD.GetHUDMovie()`.
- **Differences inside `WillowGFxHelperMap`:**
  - `FindLandmarks` picks the icon clip path from `bIsMinimap`: `"maps.landmarks"` for the minimap, `"map.maps.landmarks"` for the full map.
  - `BuildMapObjects` = `FindLandmarks`, `FindObjects`, `FindPlayers`, `FindThreats`, `FindWaypoint`.
  - The minimap subclass overrides `GetMapWidth`/`GetMapHeight` to `Invoke("GetMapWidth"/"GetMapHeight")` instead of reading `map.maps.themap._width` by absolute path.
- **Properties Enhanced added to `WillowGFxHelperMap`** (diff against classic): `bIsMinimap`, `bForceAppearanceUpdate`, `bMouseWaypointNeedsUpdate`, `InverseTransform`, `PlayerWaypoint`.

### 1.3 Flash-side evidence (Observed)

From [evidence/E_HUD_Minimap_class.as](evidence/E_HUD_Minimap_class.as) and [evidence/E_HUD_minimap_sprites.txt](evidence/E_HUD_minimap_sprites.txt):

- **Clip tree.** Sprite 187 is exported as `minimap_frame` and registered to AS2 class `Minimap` (`Object.registerClass("minimap_frame", Minimap)`).
  - Its children are `maps` (sprite 178), `northMC`, `customWaypointMC` and `currentObjectiveMC`.
  - It is placed as `map` inside each per-player HUD layout (sprites 933, 949, 958, …).
- **`maps` (sprite 178)** has one frame per zone label: `arid`, `dry`, `scrap_*`, `waste_*`, `trash`, `dlcmap1`, … Each frame contains:
  - `themap` (the zone art);
  - `landmarks` (sprite 112, with icon frames `objective`, `rstation`, `poi`, `transition`, `vss`, `bb`, `health`, `shop`, `newu`, `questionmark`, `waypoint`, `turnin`, `newmission`);
  - `players` (sprite 126, with frames `player`, `buddy1..3`);
  - `enemy`.

  Each zone frame calls `ExternalInterface.call("extInitComplete")`. The zone art is embedded in the HUD movie itself, which is why Enhanced `GfxHUD.upk` adds roughly 25 large `HUD_I2xx` textures.
- **`Minimap` methods:** `UpdateLandmark`, `AddLandmark`, `SetMapFrame`, `SetMinimapShouldRotate`, `SetMapCenter`, `CancelOutIconRotation`, `SetCurrentRotation`, `SetEdgeIconRotation`, `UpdateCustomWaypointAlignedIcon`, `UpdateCurrentObjectiveAlignedIcon`, `UpdateNorthAlignedIcon`, `rotateMap`, `SetMapScale`, `ClearLandmarks`, `RemoveLandmark`, `UpdateThreats`.
  - **`UpdateLandmark(clip,x,y,rot)`:** when the clip is `*.player`, it calls `SetCurrentRotation(-rot)`. In other words, map rotation is driven by the player icon's heading.
  - **`SetMapCenter(x,y)`:** sets `maps._x/_y`. When rotating, it calls `rotateMap(maps, -x, -y, currentRot)`, which pivots around a point using `localToGlobal`/`globalToLocal`, then counter-rotates every icon (`CancelOutIconRotation`).
  - **Edge arrows:** for the waypoint and objective, `atan2(icon - player)` gives a 0–359 frame for `customWaypointMC`/`currentObjectiveMC`. The arrow is shown only when the target is outside `|x| > 110 || |y| > 90`. So the visible window is about 220×180 local units.
  - **`UpdateThreats("idx,u,v|idx,u,v|…")`:** keeps a pool of `enemy` duplicates, positioned at `themap._x + u * themap._width` (and likewise for y). Threat coordinates are **normalised 0–1 map UVs**.
- **Root dispatchers.** The HUD root defines `AddLandmark`, `UpdateLandmark`, `ClearLandmarks`, `RemoveLandmark`, `SetMapScale`, `SetMinimapShouldRotate` and `GetMapWidth`/`GetMapHeight`. Each loops over `p1..p4` and calls `p<N>.map.<fn>(…)`. The native helper keeps calling root functions, as it does for the full map, and the HUD fans the call out to every player's minimap.
- **ExternalInterface usage:** the classic HUD makes none of the calls `extInitMinimap` / `extInitComplete` / `extNewCharInitAnimationDone`. Enhanced makes 15 / 26 / 5.

### 1.4 Native-side evidence (Observed from tables and strings; bodies encrypted)

From [evidence/E_native_exec_table.txt](evidence/E_native_exec_table.txt) and [evidence/C_native_exec_table.txt](evidence/C_native_exec_table.txt):

| Native | Classic | Enhanced |
|---|---|---|
| `WillowGFxHelperMap.InitMapFrame / InitMapFrameVars / UpdateObjects / ApplyFlash / FindObjects / FindPlayers / QuickAccessInit` | ✅ | ✅ |
| `WillowGFxHelperMap.FindWaypoint / ClearMapObjects / UpdateMapTooltips` | ❌ | ✅ |
| `WillowGFxHelperMinimap.UpdateThreats / FindWaypoint / FindPlayers / ApplyFlash` | ❌ | ✅ (the last three alias the map versions at the same addresses) |
| `WillowHUDGFxMovie.UpdateMinimap` | ❌ | ✅ `141328f90` |
| `WillowRuleEngine.IsPawnShownInRadarForCurrentState` | ✅ | ✅ |

Strings each native helper references (UTF-16 `.rdata` clusters):

- **Classic `UWillowGFxHelperMap`:** `map.mask._width/_height/_x/_y`, `map.maps.themap._width/_height`, `InitDLC`, `map.maps.gotoAndStop`, `map.Leg_Player`, `map.buddy%d._visible`, `map.Leg_Buddy%d`, `UpdateLandmark`, `AddLandmark`, `map.maps._x`, `map.maps._y`, `map.maps.players`, `buddy%d`, `player`, `map.maps.landmarks`, `rstation`, `questionmark`, `objective`.

  **Every path is absolute from the movie root, under `map`.**
- **Added in Enhanced:**
  - Invokes instead of path reads: `GetMapMaskWidth`, `GetMapMaskHeight`, `GetMapViewOffsetX/Y`, `GetMapClipWidth/Height`.
  - New calls and paths: `SetMapFrame`, `SetMapCenter` (ASCII, Enhanced only), `UpdateThreats`, relative `maps.landmarks` / `maps.players`, `InitMapFrame Got DLCMAP=%s`, `topLevel_mc.`, waypoint strings.

**Inferred:**
- Enhanced patched the native helper to branch on `bIsMinimap`: Invoke-based size queries and relative paths for the minimap, the original absolute paths for the full map.
- `UpdateMinimap(PlayerNum)` probably runs each HUD tick and does roughly: `UpdateObjects(false)` → `SetMapCenter(player map pos)` → `UpdateThreats(...)` every N ticks.

**Unknown:**
- The exact centring and world→map formula, and the threat filter. These live in encrypted code.

---

## 2. What classic already has (Observed)

- **The whole native map helper**, driven from script: `Init`, `ResetMapObjects`, `InitMapFrame`, `InitMapFrameVars`, `UpdateObjects`, `ApplyScale`, `AnalogScale`, `PanHorz`/`PanVert`, `ApplyFlash`. The status menu uses it like this ([evidence/out_C_statusmenu.txt](evidence/out_C_statusmenu.txt)):
  ```
  SetupMapPage:     ResetMapObjects(); if (!InitMapFrame(self)) extInitComplete()
  extInitComplete:  InitMapFrameVars(self); UpdateObjects(true); ApplyScale/ApplyAnalogScale; ApplyFlash(self)
  extUpdateMapPage: UpdateObjects(true); ApplyFlash(self)
  ```
  This is the same lifecycle as Enhanced `extInitMinimap` / `extInitComplete`.
- **`MapObjectData`** has script-visible fields: `TransformedLocation`, `Angle`, `Landmark`, `Player`, `WPRI`, `AS_IconPath`, `bIsDirty`. Helper fields: `DesiredCenter`, `bDesiredCenterDirty`, `ViewSize`, `ClipSize`, `Transform`, `CoordScale`, `Anchor`, `Scales`, `CurrScaleVal`.
- **The `map` clip already exists in the status menu movie** (`menus_ingame_redux.upk` → `FlashMovies.status_menu`; see [evidence/C_status_menu_map_tree.txt](evidence/C_status_menu_map_tree.txt)).
  - Root `map` (sprite 1154) contains `mask` and `maps` (sprite 1132).
  - `maps` has **the same zone frame labels and the same landmark and player icon frames** as Enhanced sprite 178. Enhanced's minimap art is clearly derived from it.
  - Root `AddLandmark`, `UpdateLandmark` and `SetMapScale` exist ([evidence/C_status_menu_landmark_fns.as](evidence/C_status_menu_landmark_fns.as)).
  - DLC zone maps are separate movies (`dlc1_maps.upk`, …) loaded through `InitDLC`.
- **No minimap profile settings, no `extInitMinimap`, no `UpdateMinimap`, no threat feed.** Classic only has the compass-strip radar (`WillowUIRadar`, `WillowRadarManager`, `p1.bearing`).

**Key consequence:** classic's native helper writes to `map.*` from the root of **whatever movie it is given**. A HUD movie that contains a root `map` clip with `mask` and `maps{themap, landmarks, players}`, plus root `AddLandmark`/`UpdateLandmark`, can be driven by the unmodified classic natives. The only missing pieces are minimap behaviours that Enhanced moved into native code (centring, threats). Both can be rebuilt in ActionScript and script.

---

## 3. Implementation plan for classic

### Approach

Don't touch the encrypted exe:
- Put the minimap UI in a **modified `GfxHUD.upk`**: a new HUD movie with a root `map` clip.
- Put the per-tick logic in a **script mod**. The preferred host is the BL1 PythonSDK ([bl-sdk/willow1-mod-manager](https://github.com/bl-sdk)), which is described as targeting "BL1 and BL1E". The fallback is a hand-written proxy DLL or UPK bytecode patching.

### Phase 0: Prove the vehicle (blocking)

> **Done.** See [PHASE0.md](../log/PHASE0.md) §2d. That section supersedes parts of Phases 2–3 below: centring stays native (script writes `DesiredCenter`), threat positions come straight from `Transform` + `CoordScale`, and the tick hook is `WillowPlayerController.PlayerTick` (`WillowHUD.PostRender` is native in classic). Probe mod: [sdk_mods/minimap_probe](../../sdk_mods/minimap_probe/__init__.py).

1. Confirm that the willow1 SDK loads in **classic** (x86, v1.5.0.0), not just Enhanced, and that it can:
   - construct UObjects (`WillowGFxHelperMap`);
   - call script functions on the HUD movie (`SetVariable*`, `Invoke`, `ActionScriptVoid`);
   - hook a tick (for example `WillowHUD.PostRender` or `WillowHUDGFxMovie` events).

   Nothing is installed in `Borderlands/Binaries` today.
2. Fallback if it doesn't work in classic: a 32-bit proxy DLL (for example `binkw32.dll`, which the game already loads) that pattern-scans `GObjects`/`GNames`/`ProcessEvent` once the SteamStub has decrypted `.text` in memory, then calls the same UnrealScript functions. The in-memory code is decrypted at runtime, so runtime pattern scanning works even though static analysis doesn't.

### Phase 1: Package tooling (have most of it)

> **Done.** See [PHASE1.md](../log/PHASE1.md): `tools/upkpatch.py` round-trips byte-identically and handles size changes (export offsets + texture bulk offsets). A resized package loaded in game with a normal HUD.

- `tools/upkdecomp.py` (LZO decompress) and `tools/upk.py` (tables) already work on both versions.
- Write `tools/upkpatch.py`. It replaces `GFxMovieInfo.RawData` in `GfxHUD.upk` (which is uncompressed), rewrites `SerialSize`/`SerialOffset` for every later export, and fixes the header. Then add new `Texture2D` exports, or reference the status menu's textures through imports.
- Round-trip test: repack the unmodified SWF, then confirm the game loads and the HUD is identical.

### Phase 2: Minimap Flash content (classic HUD movie)

> **Built:** see [PHASE2.md](../log/PHASE2.md). `tools/swfbuild.py` produces the minimap HUD movie, and it is verified offline. **Decisions closed:** see [PHASE1.md](../log/PHASE1.md) §4, which supersedes steps 1, 3 and 4 below. Zone art is vector, so it's copied with no texture exports. A root `InitDLC` handles DLC maps. Readiness is polled from the SDK. A root `MinimapRecenter()` handles the edge clamp.

Start from classic `HUD.gfx` (a FlashMovie, version 9 GFx). Edit with JPEXS FFDec (user-installed) or a scripted SWF rewriter.

1. **Copy `maps` (sprite 1132) and its dependency tree from `status_menu.gfx`** into the HUD movie: zone art, `landmarks` icon sprite and `players` sprite. Character IDs need remapping. Texture-backed bitmaps reference `status_menu`'s Texture2D exports, so either import them cross-package or duplicate them into `GfxHUD.upk`.
2. **Add a root clip named `map`** (top-right, roughly 220×180), containing:
   - `mask`: the rectangle the native reads for `ViewSize`/`ViewOffset` through `map.mask._width/_x/...`;
   - `maps`: the copied sprite, which the native moves through `map.maps._x/_y`;
   - optionally `northMC` and edge-arrow clips, ported from Enhanced `Minimap`.
3. **Add root functions** with classic signatures (the classic native calls these): `AddLandmark(clip,x,y,r,frame)`, `UpdateLandmark(clip,x,y,r)`, `SetMapScale(scale)`. Base them on the status menu versions, then layer on the Enhanced behaviours:
   - in `AddLandmark`, remember the clip when `frame == "player"`;
   - in `UpdateLandmark`, when the clip is the player icon, **recentre in AS** (`maps._x = cx - x*s`, `maps._y = cy - y*s`). This replaces Enhanced's native `SetMapCenter`. If rotation is on, apply `rotateMap` / `CancelOutIconRotation` with `-r`;
   - `UpdateThreats(str)` ported as-is (normalised UVs);
   - north indicator and waypoint/objective edge arrows ported from Enhanced (`atan2`, `|x|>110 || |y|>90`).
4. **Zone frames call `ExternalInterface.call("extInitComplete")`**, or more safely a new name like `extMinimapReady`, so the classic `WillowHUDGFxMovie` doesn't need a new script function. The SDK hook catches it, or the SDK polls `map.maps._currentframe`.
5. **Hide the classic compass strip optionally.** `p1.bearing._visible` is already a native-written path in classic.

### Phase 3: Script logic (SDK mod)

> **Built and installed:** see [PHASE3.md](../log/PHASE3.md). The mod is [sdk_mods/classic_minimap](../../sdk_mods/classic_minimap/__init__.py) and passes an 11-scenario offline integration test against the built movie. The in-game test is pending.

```
on HUD movie start / level loaded:
    helper = new WillowGFxHelperMap (outer = HUD movie)
    helper.Init(PC)                       # FindLandmarks/FindObjects/FindPlayers (classic script + natives)
    helper.ResetMapObjects()
    if !helper.InitMapFrame(HUDMovie):    # native does map.maps.gotoAndStop(<zone label>) / InitDLC
        on_ready()
on_ready (extInitComplete or frame poll):
    helper.InitMapFrameVars(HUDMovie)     # reads map.mask.* and map.maps.themap.* from HUD root
    helper.UpdateObjects(true)
    helper.CurrentScaleIdx = N; helper.ApplyScale(HUDMovie)   # or ApplyAnalogScale for fine zoom
    helper.ApplyFlash(HUDMovie)
every tick (~20 Hz, like Enhanced TickRateSeconds=0.05):
    helper.UpdateObjects(false)           # moves player/buddy icons -> AS UpdateLandmark -> AS recentres
    helper.ApplyFlash(HUDMovie)
every ~0.25 s:
    threats = [p for p in WorldInfo pawns
               if WillowRuleEngine.IsPawnShownInRadarForCurrentState(p) and within radius]
    HUDMovie.ActionScriptVoid("UpdateThreats", "i,u,v|...")
on interactive-object / mission changes (Enhanced: AddInteractiveObject, MarkMinimapDirty):
    rebuild: MapObjects.Length = 0; ClearLandmarks AS; helper.Init(PC)
```

**World → map UV for threats.** Classic has no `UpdateThreats` native and the transform math is encrypted. Fit it at runtime instead:
- After `UpdateObjects`, each landmark `MapObject` has both `Landmark.Location` (world) and `TransformedLocation` (map space). The player gives one more pair each tick.
- Solve a 2D similarity transform from at least two pairs (least squares), cache it per zone, and convert to UVs with `ClipSize`.
- The `Transform`/`CoordScale`/`Anchor` fields may give the formula directly; check them at runtime first.

**Settings.** Classic `WillowProfileSettings` has no `ShowMinimap` or `MinimapShouldRotate`. Store toggles in the mod's own config (SDK options menu) and map them to `map._visible` and AS `SetMinimapShouldRotate`.

### Phase 4: Edge cases

| Case | Handling |
|---|---|
| Split-screen (classic supports 2P) | Classic natives only know one root `map`. v1 supports p1 only. For v2, use two helper instances: since `UpdateLandmark` is root-level, route by player through a "current target" variable set before each helper update. |
| DLC zones | The classic native handles `InitDLC` (the DLC map movie loads into `map.maps`). Check that `dlcmap1` and the DLC1–3 maps work in the HUD context. |
| Full map open | The status menu owns a separate helper and movie, so there is no shared state. Pause the minimap updates while the menu is open. |
| Fast travel / level streaming | Re-run Phase 3 init on `WillowPlayerController.UpdateRadarOnLevelStreaming` / map change (that native exists in classic). |
| Performance | Enhanced updates threats at 0.05 s tick granularity. Keep `UpdateObjects(false)` cheap by limiting to `bIsDirty` objects (the native already respects `bIsDirty`). |

### Phase 5: Verification

1. Load into Fyrestone (`arid`). The minimap shows the correct frame, the player arrow is centred, and landmarks match the full map.
2. Walk and turn. The map scrolls, and in rotate mode the map rotates while icons stay upright.
3. Fast-travel to Dahl Headland (`dry`) and to a DLC zone. The map frame switches and landmarks rebuild.
4. Enemies show as red dots. Compare against classic's compass radar dots for the same filter.
5. Open and close the status-menu map. Neither map breaks the other.

### Open questions / risks

- **SDK support for classic x86 is unconfirmed.** This is the biggest risk, and Phase 0 resolves it.
- Whether the classic native `UpdateObjects` writes `map.maps._x/_y` from `DesiredCenter` on every call. If it does, it will fight the AS recentring. Two mitigations:
  - set `DesiredCenter` from the player's `TransformedLocation` each tick, so both agree;
  - or put the copied `maps` inside an extra wrapper clip that AS moves, leaving `map.maps` for the native.
- Units of `TransformedLocation` (normalised or pixels). Check at runtime with one landmark.
- Asset licensing: the mod copies Gearbox art between the user's own installed packages. Distribute a patcher, not the packages.

---

## 4. Reproducing the evidence

The tools in [tools/](../../tools/) expect decompressed packages in a sibling `pk/` folder:

```bash
python -I tools/upkdecomp.py "<game>/WillowGame/CookedPC/WillowGame.u" pk/E_WillowGame.u   # also Core/Engine/GameFramework/GearboxFramework/GFxUI
python -I tools/uedis.py E '^WillowGFxHelperMinimap\.'                                    # UnrealScript disassembly
python -I tools/swfdump.py swf/E_HUD.gfx > swf/E_HUD.txt                                   # AS2 listing (extract GFX from GFxMovieInfo first)
python -I tools/as2dec.py swf/E_HUD.txt 4061 5188                                          # Minimap class
```

`native.py` needs `pefile`, `capstone` and `numpy`. Its exec-table resolution works on the encrypted exes; its disassembly does not.
