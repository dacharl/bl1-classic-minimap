# Phase 0: script host for the classic minimap

Status, 2026-10-23: **complete.** The willow1 SDK runs on classic (2b). Run 2 solved the world → map conversion, the centring formula and the tick source (2d).

## 1. Does the willow1 SDK support classic BL1?

**Documentation says yes.**

| Evidence | Source |
|---|---|
| The mod manager is "the PythonSDK Mod Manager for BL1 and BL1E". | [bl-sdk/willow1-mod-manager](https://github.com/bl-sdk/willow1-mod-manager) |
| v2.0 and v2.1 (June) said "Enhanced is not supported". v2.2 *added* BL1E. So the original target was classic. | [releases](https://github.com/bl-sdk/willow1-mod-manager/releases) |
| v2.3 "Firehawk" (latest, 3 Jul) fixed the *classic* release zip putting the plugin loader in the wrong place. Classic ships as its own zip. | [releases](https://github.com/bl-sdk/willow1-mod-manager/releases) |
| Install guide: classic needs the **x86** VC++ redistributable and the default folder `steamapps\common\Borderlands`. The Proton override is `dsound=n,b` for classic and `dinput8=n,b` for Enhanced. | [willow1-mod-db](https://bl-sdk.github.io/willow1-mod-db/), [FAQ](https://bl-sdk.github.io/willow1-mod-db/faq/) |
| unrealsdk's `WILLOW` flavour covers "Borderlands 1, BL1 Enhanced, BL2, TPS, AoDK", in both 32-bit and 64-bit builds. | [bl-sdk/unrealsdk](https://github.com/bl-sdk/unrealsdk) |
| mods_base added BL1 in v1.10 and BL1E in v1.11. | [bl-sdk/mods_base](https://github.com/bl-sdk/mods_base) |

**Local install is compatible (Observed):**
- `Borderlands.exe` is x86, version 1.5.0.0.
- The real import names in its `.rdata` include `DSOUND.dll`, `DINPUT8.dll`, `d3d9.dll` and `XINPUT1_3.dll`. The SteamStub resolves these at runtime, so a `dsound.dll` placed in `Binaries\` is loaded through normal DLL search order. `binkw32.dll` also references `DSOUND.DLL`.
- There is no existing `dsound.dll`, `dinput8.dll` or `Plugins\` folder in `Binaries\`, so nothing will be overwritten or conflict.
- The x86 VC++ runtime 14.44.35211 is installed (registry `VC\Runtimes\X86`).

**Classic exposes every script API the minimap needs (Observed from the classic `.u` exports):**
- `GFxMovie.Invoke`, `ActionScript`, `Get/SetVariable{,Bool,Number,String,…Array}`, `WillowGFxMovie.SingleArgInvoke{B,F,S,SF}`
- `WillowHUD.GetHUDMovie`, `WillowHUDGFxMovie.Start/OnClose`
- `WillowGFxHelperMap.Init/ResetMapObjects/InitMapFrame/InitMapFrameVars/UpdateObjects/ApplyScale/ApplyFlash`
- `WillowRuleEngine.IsPawnShownInRadarForCurrentState`

**Not yet verified:** that SDK v2.3 actually loads on this install, and that `unrealsdk.construct_object` can create a `WillowGFxHelperMap` whose outer is the HUD movie.

## 2. Runtime check (needs your go-ahead)

1. Download the classic zip from the latest [willow1-mod-manager release](https://github.com/bl-sdk/willow1-mod-manager/releases/latest) and extract it over `steamapps\common\Borderlands`. This adds files only: `Binaries\dsound.dll`, `Binaries\Plugins\…` and `sdk_mods\`.
2. Build the probe with `python -I tools/build_sdkmod.py sdk_mods/minimap_probe dist`, then drop `dist\minimap_probe.sdkmod` into the game's `sdk_mods\`.
3. Launch, check that **MODS** appears on the main menu, and enable *Minimap Probe*.
4. In Fyrestone:
   - open the map, pan, then close it (this triggers the automatic dump);
   - press **F9** (HUD access + helper construct + `Init`);
   - press **F10** last (native calls against a HUD with no `map` clip; may crash).
5. Send me `sdk_mods\settings\minimap_probe_log.jsonl`. A `.sdkmod` is a read-only zip, so the log is written to the settings folder instead of next to the mod.

**What the log settles:**

| Question (from REPORT.md risks) | Log field |
|---|---|
| SDK loads, hooks fire, keybinds work | any line at all |
| Can construct the helper against the HUD | `construct` |
| Units of `TransformedLocation` (normalised or pixels) | `full_map_update.MapObjects[].transformed` vs `flash_icons` |
| Does `UpdateObjects` move `map.maps._x/_y` from `DesiredCenter`? | `full_map_update.DesiredCenter` vs `flash.map.maps._x/_y` across pans |
| World → map transform for threat dots | pairs of `world` + `transformed`, plus `Transform`/`CoordScale`/`Anchor` |
| Do the natives tolerate a movie with no `map` clip? | the `natives_*` lines (or a crash) |

**Undo:** delete `Binaries\dsound.dll`, `Binaries\Plugins\` and `sdk_mods\`. If you only want to remove the probe, delete `sdk_mods\minimap_probe.sdkmod` and `sdk_mods\settings\minimap_probe_log.jsonl`.

## 2b. Probe run 1 results (Windows, classic, Fyrestone `arid_p`)

Inputs: `sdk_mods/settings/minimap_probe_log.jsonl` (15 records: F9 twice, then F10) and `Binaries/Plugins/unrealsdk.log`.

| Question | Answer | Evidence |
|---|---|---|
| SDK loads on classic | **Yes.** unrealsdk v3.2.0 + pyunrealsdk v1.10.0; "Using Borderlands 1 hook"; waits for the Steam DRM to unpack; finds `ProcessEvent`, `GObjects`, `GNames`, `StaticConstructObject`, `StaticFindObject`. | `unrealsdk.log` |
| Read/write the HUD movie | **Yes.** `p1.bearing._visible` read `true`, toggled to `false`, then restored. | `gfx_rw` |
| Create the helper on the HUD | **Yes.** `WillowGFxHelperMap'Transient.WillowHUDGFxMovie_2:WillowGFxHelperMap_1'` | `construct` |
| Script `Init` from the HUD | **Works.** 24 `MapObjects`: 12 landmarks (`poi`/`transition`), 9 interactive objects (`vss`, `bb`, `health`), 2 `questionmark` entries with no actor, and 1 `player`. All use the absolute clip paths `map.maps.landmarks` / `map.maps.players`. Defaults: `Scales = [400,300,150,100]`, `AnchorSize = 1024×512`, `ViewBorder = 0.75`. | `hud_helper_after_init` |
| Natives against a HUD with no `map` clip | **No crash.** `InitMapFrame` returned `True`. Missing GFx paths read as `Infinity` (the HUD gives `map._width = Infinity`). `ViewSize`/`ClipSize` stay 0, so Y-derived values go `NaN` (`CoordScale.Y`, `DesiredCenter.Y`, player `TransformedLocation.Y`). | `InitMapFrame` … `hud_helper_after_natives` |
| Does `UpdateObjects` drive the centre? | **Yes, at least on the first call.** After `UpdateObjects(false)`, `DesiredCenter = (0.8869, NaN)` equals the player's `TransformedLocation`, and `bCenterDirty = True`. The native recentres on the player itself, which is what a minimap wants. So don't fight it in Flash: drop the AS recentring from REPORT §3 Phase 2 and keep only the rotation. Whether it recentres on *every* call is not yet shown. | `hud_helper_after_natives` |
| `MapObjectData.Angle` | **Raw yaw in degrees.** Player yaw −37405 UU × 360/65536 = −205.47°, exactly the logged `angle`. | player object |
| World → map transform | **`Transform` is a readable 4×4 matrix, filled in by `InitMapFrame`/`InitMapFrameVars`.** Row-vector form: `u = x·1.678e-5 + y·5.15e-8 + 0.4769`, `v = x·−2.57e-8 + y·8.378e-6 + 0.0831`. The anchor (`LevelLandmarkAnchor_0`) maps to (0, 0). Fyrestone's landmarks land in u ∈ [−0.31, 0.39], v ∈ [−0.49, 0.46], so the output is anchor-relative. The two axis scales differ by 2.003×, matching `AnchorSize` 1024:512. For threat dots, script can use this matrix directly instead of fitting one. | `Transform`, `AnchorLocation` |

**Not settled yet:**
- **The full-map hook never fired** (no `full_map_update` records). Opening the map goes through `SetupMapPage` → `extInitComplete`, and panning goes through `PanMap`. All three call `UpdateObjects` directly, so `extUpdateMapPage` probably isn't on that path. Hook those three instead. This also gives a reference run where `ClipSize`/`ViewSize` are real, not 0.
- **How the player position is logged.** The probe logged the *controller's* location (Z = −185904), not the pawn's. That's why the transform gives the player u = 0.605 while the native's `TransformedLocation.X` is 0.887. Log `Pawn.Location` so the exact `Transform` → `TransformedLocation` step (offset, `CoordScale`, `ClipSize`) can be confirmed.
- **Whether `DesiredCenter` keeps following the player** across repeated `UpdateObjects(false)` calls, and whether the native then writes `map.maps._x/_y`. The HUD has no `map` clip yet, so this can't be seen there; the full-map hook will show it.
- Pressing F9 twice created a second helper. This is harmless, but the probe should reuse the first one.

## 2c. Probe run 2 (v0.2)

**What changed since v0.1:**
- **Hooks where the full map actually refreshes:** `SetupMapPage`, `extInitComplete` and `PanMap` (throttled to 2 per second). Each record holds the helper's state plus what Flash shows: `map.maps._x/_y/_xscale/_rotation/_currentframe`, the mask and art sizes, and each icon's `_x/_y/_rotation`.
- **The player's pawn is logged,** not just its controller: `pawn_world`, `pawn_yaw`, and `pawn_uv_via_transform` (the pawn's position run through `Transform`). These sit next to the native's `TransformedLocation`. Every landmark also gets `uv_via_transform`.
- **F9 reuses the HUD helper** while the HUD movie stays the same.
- **F10 runs the native calls, then samples** `UpdateObjects(false)` twice a second for 10 s (`hud_sample` records), via a `WillowHUD.PostRender` hook.

**Steps:**
1. Optionally, rename the old `sdk_mods\settings\minimap_probe_log.jsonl` to keep run 1 separate. Run 2 also starts with a `session` record.
2. Replace `sdk_mods\minimap_probe.sdkmod` with the new `dist\minimap_probe.sdkmod`, launch, and make sure the mod is enabled.
3. In Fyrestone:
   - open the map, wait for it to draw, pan in all four directions, zoom once, then close it;
   - walk somewhere else, then open and close the map again.
4. Press **F9** once, then **F10**. For the next 10 seconds, walk in a straight line, then turn about 90°.
5. Quit and tell me. I'll read the log from the game folder.

**What it settles:**

| Question | Records |
|---|---|
| How `Transform` turns into `TransformedLocation` | `players[].pawn_uv_via_transform` vs `transformed`, with real `ClipSize`/`ViewSize`/`CoordScale` (`full_map_*`) |
| Does the native move `map.maps._x/_y` itself, and from what? | `full_map_pan.flash` vs `DesiredCenter` |
| Does `DesiredCenter` keep following the player? | `hud_sample` series while walking |
| Icon placement and rotation in Flash units | `flash.icons` vs `transformed`/`angle` |
| Which zone frame is used | `flash["map.maps._currentframe"]` |

## 2d. Probe run 2 results (v0.2, Fyrestone)

Log: 82 records after the `session` marker. That's 5 map opens (`full_map_setup` + `full_map_init_complete` each), 60 throttled `full_map_pan` records, F9 and F10. Zero `hud_sample` records (see the last row).

| Question | Answer | Evidence |
|---|---|---|
| World → `TransformedLocation` | With `(u, v) = [x y z 1] · Transform`: **`tr.x = (v + 0.5) · CoordScale.X`** and **`tr.y = (0.5 − u) · CoordScale.Y`**. The axes are swapped: world Y drives map X. The largest error over 120 objects (landmarks, interactive objects and the pawn, across 5 opens) is 9.5e-8. | `uv_via_transform` / `pawn_uv_via_transform` vs `transformed` |
| What `CoordScale` is | `CoordScale.Y = (ClipW/ClipH) / (AnchorW/AnchorH) = (3118/1408.8)/(1024/512) = 1.10662`, matching the logged value. It corrects the art's aspect ratio against the anchor's. `CoordScale.X = 1`. | `full_map_init_complete` |
| `TransformedLocation` units | **0–1 across the zone art.** Flash places icons at `themap._x + tr.x · themap._width` (same for y). The largest error over all icons is 0.05 px. This is the same convention as Enhanced's `UpdateThreats` (`themap._x + u · themap._width`), so threat dots can use `tr` directly. | `flash.icons` vs `transformed` |
| Icon rotation | `icon._rotation = Angle` wrapped to (−180, 180], where `Angle` is yaw in degrees (198.80 → −161.20). Error is 0. | player icon |
| How the native positions `map.maps` | **`maps._x = mask.cx − (themap._x + DesiredCenter.x · themap._width) · scale`** (same for y), where `mask.cx = ViewOffset.x + ViewSize.x/2`. This holds to within 0.5 px on 48 of the 60 pan samples. The 12 exceptions: (a) one sample just after opening, where the map was still easing towards its target (it animates); (b) 11 samples clamped horizontally. `maps._x` holds at 1304.8 at the left edge (`DesiredCenter.x` ≈ 0.12), and at −355.6 (first session) or −776.6 (second) at the right edge (`DesiredCenter.x` ≥ 0.87/0.91), while `DesiredCenter` keeps going. | `full_map_pan` |
| Who owns `DesiredCenter` | **Script does.** `PanMap` (via `PanHorz/PanVert`) moves it, and the following `UpdateObjects(true)` follows it without snapping back to the player. On open, the full map sets **`DesiredCenter = (player + P0) / 2`**, where P0 = (0.85886, 0.41889) is constant across 5 opens while the player moved. (Inferred: P0 is a fixed focus point such as the tracked objective. The minimap doesn't need it.) | `full_map_init_complete`, `2·DC − player` |
| Zone frame | `map.maps._currentframe = 2`, which is the `arid` label (frame 1 is `none`). This confirms the label set from the static analysis. | `flash` |
| Per-tick sampling | **Didn't fire.** In classic, `WillowHUD.PostRender` and `WillowHUD.DrawHUD` are `native` functions, called straight from C++ and never through `ProcessEvent`. Hookable per-frame script events in classic: **`WillowPlayerController.PlayerTick`** (event, script body) and **`Engine.GameViewportClient.Tick`** (event). | function flags from `tools/uedis.py` |

**What this means for the design (updates REPORT.md §3):**
- **Centring stays native.** Each tick, set `helper.DesiredCenter = player.TransformedLocation` and call `UpdateObjects(…)`. The native then moves `map.maps` so the player sits at the mask's centre. Drop the Flash-side recentring entirely. Near the left and right edges of the art, the native clamp stops the follow. In a small minimap window the player icon would then drift off-centre; if that looks wrong, offset with a wrapper clip in Flash.
- **Threat dots need no fitting.** Compute `tr` for each pawn in Python from `Transform` + `CoordScale` (above), then call the ported AS `UpdateThreats("i,tr.x,tr.y|…")`.
- **Rotation mode:** rotate `map.maps` by −(player `Angle`) around the mask centre, and counter-rotate icons, as Enhanced's `Minimap.rotateMap` / `CancelOutIconRotation` do.
- **Tick source:** hook `WillowPlayerController.PlayerTick` (throttled to about 20 Hz), not `WillowHUD.PostRender`.

Phase 0 is complete. Repeated `UpdateObjects(false)` on the HUD helper wasn't sampled, but it no longer matters: the minimap writes `DesiredCenter` itself before every update. The `PlayerTick` hook gets proven in the first Phase 3 build.

## 3. Fallback: hand-written proxy DLL

> Not needed: the SDK works on classic (see 2b). Kept for reference.

Only needed if the runtime check fails. It does the same job as the SDK, built by hand.

### Load point
- 32-bit DLL named **`dsound.dll`** in `Binaries\`. It forwards `DirectSoundCreate`, `DirectSoundCreate8`, `DirectSoundEnumerateA/W`, `DirectSoundCaptureCreate*`, `DllCanUnloadNow`, `DllGetClassObject` and `GetDeviceID` to `%SystemRoot%\SysWOW64\dsound.dll`, using a `.def` with forwarders or `LoadLibrary` + thunks.
- Alternatives if dsound is taken: `XINPUT1_3.dll` (few exports, simple to proxy) or `dinput8.dll`. All three are in the game's real import list.

### Getting past the SteamStub
- `.text` is encrypted on disk but decrypted in memory before the stub resolves imports and jumps to the original entry point. Do nothing heavy in `DllMain`. Start a worker thread that waits until a known code signature appears in `.text`, retrying every 100 ms for up to about 10 s, then initialises.
- **One-time bonus:** have the DLL write the decrypted `.text` to disk. That dump gives patterns for the steps below. With Ghidra 12.1 installed and `GHIDRA_INSTALL_DIR` set, it also lets REA decompile the native code statically, including Enhanced's `execUpdateMinimap` (from a dump of the x64 game) to settle the "Unknown" rows in REPORT.md.

### Engine access (UE3 v584, x86)

| Need | How |
|---|---|
| `GNames`, `GObjects` | Pattern-scan the dump. These are `TArray`s of `FNameEntry*` / `UObject*`, and are validated by checking that `GNames[0] == "None"`. |
| `UObject` layout | Offsets for `Name`, `Class`, `Outer` and `Index`, confirmed by walking `GObjects` for `Class Core.Object`. |
| `ProcessEvent` | The `UObject` vtable slot. Find it by scanning the dump for the `ProcessEvent` prologue, or by matching the slot that changes behaviour when a known event fires. Hook it with MinHook. |
| Calling UnrealScript functions | `StaticFindObject`, or a `GObjects` scan for `Function WillowGame.WillowGFxHelperMap.InitMapFrame`, then `ProcessEvent(obj, func, &params)`. Parameter order and types come from the package (`tools/uedis.py` lists them). Byte offsets are computed at load time, so read them from the live `UProperty::Offset` fields by walking `UFunction::Children` in memory. |
| Creating the helper | Pattern-scan `StaticConstructObject(UClass*, UObject* Outer, FName, flags, template, …)`. |
| Tick | Hook `ProcessEvent` and act on `WillowHUD.PostRender` (an event in classic) or `GearboxGFxMovie.OnTick`, throttled to 20 Hz. |
| GFx calls | Plain UFunction calls: `GFxMovie.SetVariableNumber`, `Invoke`, `ActionScript`. These reach the classic natives. |

### Cost and risk compared with the SDK
- The SDK already has all of the above (GObjects/GNames discovery, hooks, `construct_object`, typed property access). The fallback rebuilds it for one game version: days to weeks of work, and every pattern breaks if Steam ships a new exe.
- The minimap logic is the same either way (REPORT.md §3, Phase 3). Only the host changes.

## 4. Next step
Once the probe log is back, Phase 1 (the `GfxHUD.upk` patcher) and Phase 2 (Flash content) can start. Their exact design depends on the `DesiredCenter` and `TransformedLocation` answers.
