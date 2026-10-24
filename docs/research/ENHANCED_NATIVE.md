# Enhanced minimap natives, decompiled, and how they map to classic (2026-10-24)

This doc covers the native C++ side of the Enhanced minimap, read from Ghidra pseudocode of decoded executables. It also compares each piece with classic's own natives. [REPORT.md](REPORT.md) §1 covers the UnrealScript and Flash side; this fills in what REPORT.md marked "encrypted / unknown".

## Inputs and method

| | Classic (x86, base `0x400000`) | Enhanced (x64, base `0x140000000`) |
|---|---|---|
| Protected exe SHA-256 | `71b58c40…dc42a` | `57c5dc7b…9ef56` |
| Protection | SteamStub 2.1 x86 | SteamStub 3.1 x64 |
| Decoded copy (`tools/steamstub.py`) | `dist\decoded\Borderlands.decoded.exe` = `d3e941db…b5da` | `dist\decoded\BorderlandsGOTY.decoded.exe` = `92b53f7f…b5a2` |

- **Decoded copies:** both hashes match the steam-deck-scripts research copies exactly. The copies change only the encrypted code range, so file offsets and VAs equal the shipped exe's, and that research's addresses apply as-is.
- **Analysis:** REA 6.7.0 with the Ghidra 12.1.4 provider, full auto-analysis minus five slow analyzers (see PROGRESS). It runs through `tools/rea_client.py`, which keeps one REA MCP server per binary alive, because each import takes 15–18 minutes.
- **Raw pseudocode:** `dist\rea\{cls,enh}\fn\<addr>_<name>.c`. The REA Evidence JSON is alongside in `dist\rea\{cls,enh}\batch*.json`.

| Evidence ID | Contents |
|---|---|
| `ev_2050c93b…` | classic: ApplyFlash, InitMapFrame, InitMapFrameVars, UpdateObjects, FindPlayers, FindObjects |
| `ev_7da1cf35…` / `ev_c8e0a979…` | classic: transform builder, projection, anchor matrix |
| `ev_46cb5212…` | Enhanced: scheduler, HUD updater, UpdateMinimap, minimap ApplyFlash, InitMapFrame, InitMapFrameVars, UpdateObjects, FindPlayers, FindWaypoint, UpdateThreats, ClearMapObjects |
| `ev_6f7319ed…` / `ev_fc5b919e…` / `ev_2c62792d…` | Enhanced: threat collector + projection; FindObjects; waypoint mission info |

**How sure each claim is:**
- Control flow, arithmetic, Flash call names and arguments are read directly from pseudocode (**Observed**).
- Turning raw offsets into property names (e.g. `+0x108` = `Anchor`) is **Inferred**: it rests on the property's declaration order, on how the value is used, and on matches between editions, not on linked property metadata.
- Nothing here was observed running; runtime behaviour comes from the in-game runs in PHASE3.md.

## 1. The per-frame pipeline (Enhanced)

```
GearboxHUD scheduler (vtbl+0x330)      @140ad55f0  first frame, or Interval(+0xFC)>0 && now-last > Interval
  └ WillowHUD updater (vtbl+0x350)     @1413cb7e0  per split-screen player i: ready byte(+0x248+i) && PC && Pawn && PRI
      └ per-player HUD slot list (vtbl 0x378…0x408) → UpdateMinimap(movie)
UpdateMinimap                          @1413e7970
  helper = movie+0x142C; return if null
  if movie.flags(+0x1B0) & 8:  clear; ProcessEvent(RebuildMinimapObjects)   # bRebuildMinimapObjects
  UpdateObjects(helper, true)          @1413ad210
  helper.UpdateThreats(movie)  (vtbl+0x260)  @1413eab00
  helper.ApplyFlash(movie)     (vtbl+0x238)  @1413b6230
```

- **Visibility:** the gates are only "player ready + controller/pawn/PRI exist". There is no loading-movie, menu or visibility test in native code. Enhanced hides the minimap because the whole HUD movie (`p1`) is hidden or replaced. Classic's mod has to gate visibility itself (PROGRESS fact 8 stays).
- **Interval:** `Interval` is a float on the HUD (the earlier research found a Start value of 0.05). The mod's `TICK_INTERVAL = 0.05` matches it.

## 2. Side-by-side: every native the minimap uses

| Step | Enhanced | Classic | Difference that matters |
|---|---|---|---|
| Frame select | `InitMapFrame` @141391fd0 | @1424c70 | Identical logic: Anchor → `MapFrame` string; `DLCMap` set → `InitDLC(frame, "<pkg>")`. The only change is that the minimap calls `Invoke("SetMapFrame")`; the full map and classic call `Invoke("map.maps.gotoAndStop")`. |
| Frame vars | `InitMapFrameVars` @141392590 | @141cca0 | Same arithmetic. Enhanced minimap reads sizes via `Invoke("GetMapMaskWidth/…/GetMapClipHeight")`; classic reads the absolute paths `map.mask.*` / `map.maps.themap.*`. |
| Transform | inline in UpdateObjects | `FUN_014140b0` → anchor `FUN_0146bd60` | Same: forward matrix from the anchor actor, then `D3DXMatrixInverse` (see §3). |
| Projection | `FUN_1413ab090` | `FUN_01414000` | Identical formula: `tr.x = (q.y+0.5)·CS.X`, `tr.y = (0.5−q.x)·CS.Y`. |
| Object update | `UpdateObjects` @1413ad210 | @1416240 | Same record walk, pawn yaw × 360/65536, WPRI and landmark sources, ordinal waypoint re-read, 0.1–0.9 no-anchor auto-fit. |
| Objectives | `FindObjects` (fn @14138b500) | @1420f90 | **Changed.** Classic sets the waypoint bit, so UpdateObjects re-reads slot k for the k-th record. Enhanced **copies** the location and chooses `objective`/`turnin`/`newmission` from mission status (§4). |
| Custom pin | `FindWaypoint` @1413c2350 | absent | Enhanced-only player map pin (`PC+0xB94&2`, `PC+0xE28`, clips `waypoint1..4`). Not needed for classic. |
| Threats | `UpdateThreats` @1413eab00 + `FUN_141487bd0` | absent | Reads the **compass radar's replicated icon list** (§5). |
| Flash output | minimap `ApplyFlash` @1413b6230 | @142a420 | Same Add/UpdateLandmark loop. Enhanced replaces classic's clamped `map.maps._x/_y` pan with per-player `SetMapCenter` (§6). |
| Clear | `ClearMapObjects` @141388410 | absent | Tail call that empties the record array, used by the rebuild event. Classic equivalent: a fresh helper (what the mod does). |

## 3. Transform: Step B is confirmed and corrected

Classic anchor matrix (`FUN_0146bd60`, a method on the `LevelLandmarkAnchor` actor; Enhanced's is the same):

```
R      = rotation from Rotation (Pitch +0x68, Yaw +0x6C, Roll +0x70) via the engine sine table
X axis = R.X · TextureSizeX(+0x1FC) · DrawScale3D.X(+0x78) · DrawScale(+0x74)
Y axis = R.Y · TextureSizeY(+0x200) · DrawScale3D.Y(+0x7C) · DrawScale
Z axis = R.Z                        (unscaled)
origin = Location (+0x5C)
Transform (helper +0x110, 4×4) = D3DXMatrixInverse(forward)
q = [x y z 1] · Transform
```

**Correction to PROGRESS's Step B formula:** the extents also include **DrawScale**, and pitch/roll take part. On a flat anchor (pitch = roll = 0) with DrawScale = 1, it reduces to the PROGRESS formula, which is why the Arid fit was exact. Step B should build the full matrix, or at least multiply by DrawScale and assert that pitch and roll are 0.

**CoordScale:** `InitMapFrameVars` starts from AnchorSize (helper `+0x150/0x154` classic, `+0x200/0x204` Enhanced) and ClipSize (`themap` W/H, `+0x160/0x164` classic). With `fx = A.x/Clip.w` and `fy = A.y/Clip.h`:
- if `fy < fx`: `CS.X = A.x/(Clip.w·fy)`;
- otherwise: `CS.Y = A.y/(Clip.h·fx)`.

The other component keeps its prior value (default 1). This matches the CoordScale formula already in PROGRESS.

## 4. Objective markers

- **Classic** (`FindObjects` @1420f90): for each non-zero `GRI.ActiveWaypointData[k]` (`GRI+0x2B0`, 8 × 16 bytes, gated on `GRI+0x334`) it appends an `objective` record with the waypoint bit set. `UpdateObjects` gives the n-th waypoint-bit record the n-th slot in order. A zero slot at update time skips the record (it stays stale) but still advances n, so records drift between slots when slots empty or refill. **This is the root cause of the stale diamonds seen in v0.5.0**, and v0.5.1's key-change rebuild is the correct fix.
- **Enhanced** (`FindObjects` @14138b500, objective loop at `0x14138c3xx`):
  - It reads the same slots (`GRI+0x364`) but copies each location into the record without the waypoint bit, so the marker stays static until the next rebuild.
  - It chooses the icon per slot from `FUN_14138d240`, which walks the controller's current playthrough mission list (`PC+0x1414`, playthrough from `vtbl+0xEF8`, 0x1C-byte entries, status byte `+8`). Status 2 (ready to turn in) gives `turnin`, status 0 gives `newmission`, anything else gives `objective`. It also attaches tooltip strings (`MapTooltips`, `%s_body`).
  - Rebuilds come from `bRebuildMinimapObjects`, which the mission and interactive-object script setters raise through `MarkMinimapDirty`.

**Mapping:** the mod's model (rebuild whenever mission, target, turn-in, slot locations or live levels change) already equals Enhanced's, without depending on script setters. What's missing is the **icon type**. The mod can add it by reading the tracked mission's status from `WillowPlayerController` mission data (classic has the same playthrough/mission-status structures) and sending `turnin` or `newmission` instead of `objective`.

## 5. Threats: Enhanced reuses the compass radar's data

`FUN_141487bd0`:
- **Where it reads:** `GetLocalPlayer(0)` → `+0x450` → cast (`FUN_141267740`) → `+0x3E8` object. Inferred to be `WillowGameReplicationInfo.RadarMgr` (`WillowRadarManager`).
- **What it copies:** while the found count is below `+0x338`, inferred to be `NumberOfDynamicIcons`, it scans entries at `+0x540`. Each entry is 24 bytes, at most 18 of them; that bound is the script const `MAX_ACTIVE_DYNAMIC_ICONS = 18` in both editions. An entry with `bActive` (`+0x10 & 1`) contributes its `Location`.
- **Matching struct:** `RemoteDynamicRadarIconData {Location, IconType, FadeStartTime, bActive}`, i.e. `RadarMgr.RemoteDynamicIcons[18]`.
- **No filtering:** there is no range check, no `IconType` filter and no rule-engine call. Every active dynamic radar icon becomes a dot.
- **What `UpdateThreats` does with them:** it projects each one, joins them as `"%d,%f,%f|"` and calls `Invoke("UpdateThreats", s)`, skipping the call when the count goes from 0 to 0.

**Mapping:** classic has the same `WillowGameReplicationInfo.RadarMgr`, `RemoteDynamicIcons`, `NumberOfDynamicIcons` and the identical `ERadarIconType` enum (None, Gunfire, Threat, BountyBoard, Shop, Health, NewU, CatchARide, Settlement, MissionNPC, NamedNPC, Loot, Objective, Checkpoint).
- So the mod can replace its pawn scan (`IsEnemy`, range, `IsPawnShownInRadarForCurrentState`) with a read of `GRI.RadarMgr.RemoteDynamicIcons`. That gives exactly what Enhanced shows and what classic's own compass radar shows, at lower cost, and it is replicated so it works for co-op clients.
- Keep the "Show enemies" option. "Enemy range" could become an optional extra filter.

## 6. Centring

Enhanced minimap `ApplyFlash`, when the center-dirty bit `8` is set: for each split-screen player N, take `PC+0x260` → Pawn, project `Pawn.Location (+0x90)`, then call `SetMapCenter("p<N>", −tr.x·ClipW, −tr.y·ClipH)` with ClipW/ClipH = `themap` size. There is no mask term and no clamp. Map rotation is done in Flash (`Minimap.UpdateLandmark` on `*.player` → `SetCurrentRotation(−angle)`).

Classic `ApplyFlash` instead computes a clamped pan from `DesiredCenter`, mask and clip and writes `map.maps._x/_y`.

**Mapping:** the mod's `tick~u~v~deg` command already does Enhanced's centring in AS2 (PHASE0 §2c), so nothing changes.

## 7. What this changes in the mod

**Status:** v0.6.0 implements items 1, 2, 4 (as a tint, because classic art lacks the frames) and 5. For item 3, it keeps classic's own list builders through a one-call helper (see PHASE3 §3k and PROGRESS open items).

1. **Threats** from `GRI.RadarMgr.RemoteDynamicIcons` (where `bActive`, up to `NumberOfDynamicIcons`) instead of scanning pawns. This matches Enhanced and the classic compass exactly, and works on co-op clients.
2. **Step B** with the full anchor matrix (rotation + `TextureSize · DrawScale3D · DrawScale`) and `D3DXMatrixInverse`-equivalent maths, rather than the yaw-only formula. That removes the transient helper for transform and frame. Landmarks still need a source (see 3).
3. **Without a helper**, landmarks come from the same lists FindObjects walks:
   - level landmarks: list `[0x3D]/[0x3E]`, type byte `+0x328 < 14`, icon by type;
   - interactive objects: `rstation`/`questionmark`;
   - waypoint slots: `GRI.ActiveWaypointData`.

   Their exact script-visible names still need confirming with an SDK probe.
4. **Objective icon type** (`turnin`/`newmission`) from mission status.
5. **Visibility gating stays mod-side.** Enhanced has none natively.

## Open / not checked

- **Offset → name bindings:** all are inferred from layout. Confirm the radar fields (`RadarMgr`, `RemoteDynamicIcons`, `bActive`, `NumberOfDynamicIcons`) with a one-line SDK read before relying on them.
- **FindPlayers:** decompiled in both editions but not diffed in detail. Co-op buddy markers are unchanged in intent; Enhanced adds `p1.coop%d` HUD slots in the updater.
- **Rotation:** the rotation-table initialisation and DLC `InitDLC` asset loading are unchanged from the earlier research's open items.
