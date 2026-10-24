# v0.8 plan: Enhanced zoom, edge indicators, mission givers (2026-10-24)

**Implemented as v0.8.0** (PHASE3 §3m).

Run 10 (v0.7.0) confirmed the v0.7 fixes: T-Bone is correct, and Skag Gully's waypoints and the ECHO placement are right. Enhanced footage shows three things we lack: a closer zoom, north/objective indicators riding the minimap edge, and "!" mission-giver icons.

## Research (evidence)

### 1. Zoom

- **Script** (`tools/uedis.py E`): `extInitComplete` sets `CurrentScaleIdx = 3`, then `ApplyScale` → `SetMapScale(Scales[3])`, then `AnalogScale(self, 1.0)`.
  - `AnalogScale` = `FClamp(CurrScaleVal + 1.0·ZoomSpeedFactor, MinScale, MaxScale)` → `SetMapScale`.
  - **Defaults** (`tools/upkprops.py`, both editions): `Scales = [400, 300, 150, 100]` (ints), `ZoomSpeedFactor = 8`, `MinScale = 100`, `MaxScale = 400`. The Minimap subclass overrides nothing.
  - So Enhanced's minimap art is at **108%**.
- **Art size:** the same in both editions (arid `themap` shape 776×352 in E sprite 87, 779.5×352 in classic 1046).
- **On screen:** Enhanced = 1.08 (`themap`) × 0.7 (map in `p1`) = **0.756 px per art unit**. v0.7 docked = 3.00 (300% option) × 0.187 (dock) = 0.561.
- **Equivalent for us:** relative to the window, 108% × (820.75 / 220) = **403%**.
- **Icons:** the landmark and player art is identical too (E sprite 112 = classic 1066 frame for frame; objective at 0.55). Enhanced draws icons at the map clip's 0.7; ours draw at 0.187 because icons live in the unscaled `maps`. Matching Enhanced means icons (and threat dots) at **820.75/220 = 3.73×**.

### 2. Edge indicators (E_HUD Minimap AS class, `scratchpad/swf/E_Minimap_class.as`)

- `northMC` (sprite 182), `currentObjectiveMC` (186) and `customWaypointMC` (184) are 360-frame sprites placed at (0, −55) in the minimap clip. Each frame moves an `align_point` child along a rectangle of ±110 × ±92 around the minimap centre, the window border; frame n = angle n.
  - North shows the `north` art (char 180 → shape 179).
  - The objective shows the objective diamond at 0.55.
- `SetEdgeIconRotation(clip)`: angle = `atan2(icon − player)·180/π + 90` (+ `currentRot` when rotating).
- `UpdateCurrentObjectiveAlignedIcon`: `gotoAndStop(angle)`; visible (`_alpha` 100) only while the target is outside the window (`|y| > 90 || |x| > 110` in minimap-local coordinates, via `localToGlobal`/`globalToLocal`).
- North is always shown at `currentRot` (top when not rotating).
- The tracked objective is the last icon added with the `objective` frame (`currentObjectiveClip`). The custom waypoint is Enhanced-only (map pin).

### 3. "!" mission givers

- **Enhanced:**
  - `FindObjects` (native, fn @14138b500) pairs `GRI.ActiveWaypointData` slot *i* with entry *i* of a list built by `FUN_14138d240`: missions ready to turn in from `MissionPlaythroughData[pt].MissionList` (status 2), then every status-0 entry of **`NonStartedMissionData`**. Type 2 gives the `turnin` frame, type 0 gives `newmission` ("!").
  - **`WillowPlayerController.NonStartedMissionData` is an Enhanced-only property** (absent in classic WillowGame.u), and so is the slot filling that goes with it. Classic can't reuse this path.
- **Classic equivalent (script):**
  - Only `WillowInteractiveObject` implements `IMissionDirector` (NPC givers are interactive objects).
  - `GetEligibleMissions(WPC)` counts the `MissionDirectives` with `bBeginsMission` and `WPC.GetMissionEligibility(def) == 0`: not in the mission list, level and dependencies met, not tracked.
  - `GetRedeemableMissions(WPC)` counts `bEndsMission` directives with `IsMissionInStatus(def, 2)`.
  - These are the classic game's own availability rules; they also drive `AnnounceEligibleMissions`.
- **Art:** classic's landmark sprite has no `turnin`/`newmission` frames. Enhanced's are vector shapes 108 (turn-in) and 110 ("!"), with no bitmaps, so they copy safely.

## Plan

1. **Movie (`swfbuild.py`):**
   - Copy E shapes 108, 110 and 179 as ids 1301, 1303 and 1305, with one-frame wrapper sprites.
   - Append frames 11 `turnin` and 12 `newmission` to the landmark sprite 1066 (remove depths 2/1, place the art at depth 1, as E 112 does).
   - Export `bl1mm_north` (the north art) and `bl1mm_objective` (classic objective art).
   - `_root.mmIconScale`: `add` and `MinimapPlayer` scale new icons, and threat dots use it.
   - The `add` command records `objective` icons in `_root.mmObjectives`.
   - New `MinimapEdges(rotate)` (run by `tick` after recentring): the north indicator at angle `R` (map rotation; top when north-up), and one edge diamond per off-window objective. Each sits at the intersection of the ray from the mask centre with the mask rectangle, inset by half an icon. Off-window uses the same rule as Enhanced (outside the window), computed in `map` coordinates from `maps`' translation and rotation.
2. **Mod:**
   - **Zoom:** "Zoom (vs Enhanced)" = 100% (default) / 125% / 150% / 75% / 50%. `themap` scale = 108 × 820.75/220 × factor (403% at 100%), for docked and custom alike. A new option identifier, so old "300%" settings don't carry over.
   - **Icon scale:** 820.75/220 × "Icon size" (default 100%).
   - **Givers:** at collect, list the interactive objects with non-empty `MissionDirectives` (`WillowGlobals.ClientInteractiveObjects`). For each, `GetRedeemableMissions(pc)` > 0 gives `turnin`; otherwise `GetEligibleMissions(pc)` > 0 gives `newmission`, at `Location`. Then:
     - the giver states are part of the rebuild key, so accepting or turning in a mission updates the icons in place;
     - an option "Show mission givers" (default on);
     - if a call fails, warn once and skip givers.
3. **Tests:**
   - **AS:** the new frames exist; icon scale is applied; objectives are recorded; edge indicators (inside → hidden, outside → on the border along the ray, rotation-aware north); clear resets.
   - **Mod:** zoom maps to 403%; icon scale; givers (eligible → "!", redeemable → turnin, none → nothing); accepting a mission rebuilds in place; failing calls are skipped.
4. **Build, install, docs:** PHASE3 §3m, PROGRESS.

## Not done here

- Enhanced's custom map pin (`FindWaypoint`, Enhanced-only).
- Co-op buddy markers.
- Tooltips.
