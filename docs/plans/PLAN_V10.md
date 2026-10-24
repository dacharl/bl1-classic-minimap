# v0.10 plan: Enhanced's fit-to-objectives zoom and a clean edge handoff (2026-10-24)

**Implemented as v0.10.0; not installed or verified in game.** See PHASE3 §3v.

Run 13 (v0.9.0, PHASE3 §3u) compared classic with Enhanced footage at the same spot (the Skag Gully sign in Arid Badlands) and found three things:
1. Enhanced's map is drawn about 2.5–3× closer. The box and window are the same size on screen in both.
2. With the objective due north and outside the window, its edge diamond overlaps the **N** marker.
3. An objective just inside the top of the window shows as a sliver: most of the icon is clipped.

## Research (evidence)

### 1. Zoom: "108%" was only the no-objective case

**Ruled out:**
- **Art:** both editions draw the same art. The Enhanced Arid shape (86, inside sprite 87) is 776.0 × 352.2 units; classic's (1045) is 779.5 × 352.2. Wireframe renders of both (scratchpad `shaperender.py`) show the same layout and the same road-dot spacing (about 4.75 units).
- **Classic's own scale:** classic is at 108% as designed. Run 13's F7 log shows `themap_w` 841.85 = 779.5 × 1.08.
- **Ini overrides:** no ini in either the Enhanced install or Documents overrides the helper's `Scales`/`MinScale`/`MaxScale`. The package defaults are confirmed: `Scales` = int[400, 300, 150, 100] (`findints.py`), Min 100, Max 400, ZoomSpeedFactor 8.

**The measured gap:** on a 2000-px-wide frame, the road dots are about 15 px apart in the footage and about 5.7 px in classic. That makes Enhanced about 2.7× closer, roughly 290%.

**The step v0.8 and v0.9 missed:** `WillowHUDGFxMovie.extInitComplete` runs:
```
ApplyScale (Scales[3] = 100)
MapHelper.QuickAccessInit()     <- native, previously treated as unrelated
AnalogScale(+1.0)               -> +8
```
The native's name gave no clue about the zoom, so its body was never read.

**Locating it** (decoded Enhanced exe; scratchpad `nativeptr.py`, `qwords.py`, `dis64.py` with capstone, no Ghidra import needed):
- The native table entry `{"UWillowGFxHelperMap" "execQuickAccessInit", 0x1412ee5f0}` sits at `0x1424f7dd0`.
- The thunk at `0x1412ee5f0` jumps through the helper's vtable at `+0x258`.
- In the minimap helper's vtable (base `0x141ed10d0`), that slot holds `0x14139a970`.
- The vtable alignment checks out against ENHANCED_NATIVE: `+0x238` = minimap `ApplyFlash` `0x1413b6230` and `+0x260` = `UpdateThreats` `0x1413eab00`.

**What `QuickAccessInit` (`0x14139a970`) does.** Control flow and arithmetic are **observed**. Field names are **inferred** from offsets that match the recorded `InitMapFrameVars` decompile (`dist\rea\enh\fn\0x141392590_InitMapFrameVars.c`) and the script.
1. **Points:**
   - The player: `PlayerOwner(+0x158).Pawn(+0x260).Location(+0x90)`, if there is a pawn.
   - Every non-zero slot of `GRI.ActiveWaypointData[0..7]`. The GRI is reached as `GetLocalPlayer(0)+0x450`, cast, then `+0x364` with a 16-byte stride, the same slots `FindObjects`/`UpdateObjects` read (ENHANCED_NATIVE §4). This read is gated on `+0x3E8` (`RadarMgr`) being non-null.
2. **Fewer than two points:** nothing changes; `CurrScaleVal` stays 100.
3. **Bounding box:** take the world bounding box's min and max corners (x, y, z). Its centre is projected and stored in `DesiredCenter` (`+0x228`). Only the full map pans to that; the minimap centres on the pawn (ENHANCED_NATIVE §6).
4. **Project the corners** with the same projection as the mod's `to_map`: u = (T.y + 0.5)·CS.x, v = (0.5 − T.x)·CS.y.
   - Multiply by `ClipSize` (`+0x210/+0x214`, the `themap` size at the current scale) and divide by `CurrScaleVal` (`+0x2CC`). That gives art units per 1%.
5. **Fit:** raw = 0.5 × min(MaskW / du, −MaskH / dv). `MaskW`/`MaskH` (`+0x218/+0x21C`) come from `GetMapMaskWidth`/`Height`. So the points' box spans **half the window**.
6. **Clamp:**
   - `CurrScaleVal` = `MinScale` (100) if raw < 100, else min(raw, `MaxScale` 400).
   - `CurrentScaleIdx` = the nearest `Scales` entry; the centre-dirty flag 8 is set.
7. **Then `AnalogScale(+1)`:** clamp(`CurrScaleVal` + 8, 100, 400) goes to `SetMapScale`.

**Consequences:**
- **Enhanced's zoom is 108% only when no objective is active.** With objectives it fits them, up to 400%.
- **Every objective starts inside the window.** The window is centred on the player, and the points' box spans half the window, so no point can be further than half a window from the player.
- **It is computed once per HUD init** (`extInitComplete`, after a level load). Nothing else in HUD script calls `QuickAccessInit`, `AnalogScale` or `CycleScale` (full Enhanced script dump, `uedis.py E .`), and no native names them. Objective changes therefore do not refit.
- **Unknown:** whether `extInitComplete` also runs after respawn.
- **Footage check (inferred):** the footage's "Skags killed 0/5" objective lies near Skag Gully. The measured ~290% is inside the formula's range.

**Classic has the same native** (`WillowGFxHelperMap.QuickAccessInit`; its status menu calls it when `QuickAccessScreen == 4`). Since v0.9, classic's `map.mask` is Enhanced's window, so every input exists in Python: the pawn, `GRI.ActiveWaypointData[i].WaypointLocation` (already read by `waypoint_key`), `S.xf`, `S.cs`, the art size and the mask size.

**Worked example** (Arid's recorded Transform and CoordScale from run 13's F7 log; art 779.5 × 352.2; player at the origin; scratchpad `fitzoom.py`):

| Waypoint (world offset) | raw | Final zoom |
|---|---|---|
| none | — | **108** |
| (+2000, +3000, 0) | 531.8 | **400** (clamped, +8 clamped) |
| (+6000, +9000, 0) | 177.3 | **185.27** |
| (+20000, +30000, 0) | 53.2 | **108** (raised to 100, +8) |

### 2. Edge indicators: what Enhanced does

The source is Enhanced's `Minimap` AS class (E_HUD `DoInitAction` for sprite 187): `UpdateCurrentObjectiveAlignedIcon` and `UpdateCustomWaypointAlignedIcon`.
- **Test:** each one converts its clip's position to minimap coordinates (`maps.localToGlobal` → `globalToLocal`). The edge indicator gets `_alpha` 100 when |x| > 110 or |y| > 90, and 0 otherwise. **The in-map icon is never hidden.**
- **Count:** there is one objective indicator (`currentObjectiveClip`, the last `objective` icon added), one custom-waypoint indicator, and north, which is always shown.
- **Art and path:**
  - `currentObjectiveMC` frames hold sprite 185, the landmark objective art at 0.55× (classic's `OBJECTIVE_SCALE` is the same).
  - Frame 1 places it at (0, −37.1); with the clip at (0, −55), that is (0, −92.1). Frame 90 lands at (109.8, 1.0).
  - That is the ±110 × ±92 path v0.9 already uses.
- **Overlap:** north is at depth 19, the custom waypoint at 21 and the objective at 23, so the objective draws over **N**, and there is no avoidance code. **Run 13's overlap screenshot matches Enhanced.**
- **Clipping in Enhanced:** the window spans ±103.975 × ±86.825, and Enhanced's thresholds (110/90) lie outside it.
  - An objective whose centre falls between the window edge and the threshold is drawn clipped with no edge marker. That is run 13's sliver.
  - Past the threshold, the clipped sliver and the edge marker both show until the icon leaves the window. That is run 12's "double".
  - So **both artefacts are Enhanced's own behaviour.**
- **Classic now (v0.8.1/v0.9):** the icon shows while its centre is inside the ±110 × ±92 ray rectangle (`t > 1`); otherwise only the edge diamond shows. That makes the sliver band 86.8 → 92 in y.
- **Classic's objective icon** (char 1050 at 0.55 in landmark sprite 1066) is 45.1 × 0.55 ≈ **24.8 units**, a half-size of 12.4 at Icon size 100%.

## Plan

1. **Zoom (mod):**
   - New pure function `fit_zoom(points, xf, cs, art_w, art_h)` that reproduces `QuickAccessInit` + `AnalogScale(+8)` exactly:
     - corner-only projection;
     - half-window fit against `MASK_W`/`MASK_H`;
     - clamp order: raise to `MinScale`, otherwise cap at `MaxScale`; then +8; then clamp.
   - **Points:** `pc.Pawn.Location` (if there is a pawn) plus each non-zero `GRI.ActiveWaypointData[i].WaypointLocation`, read in `collect()`.
   - **When:**
     - fit on a fresh capture (startup, level load, new anchor) and on F8 / "Rebuild now";
     - keep the fit through in-place objective rebuilds, since Enhanced refits only at HUD init.
     - Store the result in `S.fit`.
   - **Art size at 100%:** `themap._width × 100 / themap._xscale`, read at capture (the current scale may already be applied).
   - **Option:** `themap` scale = `S.fit` × the "Zoom (vs Enhanced)" factor, so 100% now means "Enhanced's fitted zoom". Same option identifier; no settings migration.
   - **F7:** add `zoom_fit` = {points, raw, fitted, final}.
     Follow-up: confirm the diagnostic write in the in-game console via
     `pc.Player.ViewportClient.ViewportConsole.OutputText(Text)`. Classic's C_Engine.u exports confirm
     the LocalPlayer/viewport property chain and the one-string signature; Console.OutputTextLine appends
     to Scrollback and updates ConsoleBufferText. Keep the SDK snapshot if console feedback fails.
2. **Edge handoff (movie, `MinimapEdges`):**
   - **Inside** means the whole objective icon is inside the window: |dx| ≤ hw − r and |dy| ≤ hh − r. Here r = max(`o._width`, `o._height`) / 2 × k, the icon's half-extent in `map` coordinates (`maps` scale k; the icon is counter-rotated, so max() covers any angle).
   - **Inside:** the icon is visible and its edge diamond hidden.
   - **Otherwise:** the icon is hidden and the edge diamond sits on Enhanced's ±110 × ±92 path (position unchanged).
   - **Result:** no sliver and no double. This deliberately deviates from Enhanced, which shows both artefacts.
   - The diamond jumps from the inset line (about 74 units, y) to the path (92). That is small and keeps the direction.
   - **Alternative (not recommended):** hand over at the window edge (icon centre inside). It leaves at most half an icon clipped and avoids the jump.
3. **North overlap: no change.** This is Enhanced's behaviour (objective drawn over N). A nudge along the border would misstate the direction by a few degrees; leave it unless you want it.
4. **Tests (red first, one behaviour at a time):**
   - **Mod:**
     - the worked-example rows with Arid's recorded Transform (108 / 400 / 185.27 / 108);
     - zero slots are ignored;
     - no pawn plus one waypoint gives 108 (fewer than two points);
     - the 150% option gives fit × 1.5;
     - an in-place objective rebuild keeps the fitted zoom; a new anchor and F8 refit;
     - F7 reports `zoom_fit`.
     - The fakes' `ActiveWaypointData` slots get `WaypointLocation` (already shaped for `waypoint_key`).
   - **AS:** the objective source clip gets the real 24.8-unit icon size.
     - dy = −80: the centre is inside the window, but the icon crosses its edge (86.8 − 12.4 = 74.4), so the icon is hidden and the diamond sits at y = −92.
     - dy = −70: the icon shows and the diamond is hidden.
     - dx = 95 → diamond; dx = 90 → icon.
     - At Icon size 150% (r = 18.6), dy = −70 → diamond.
5. **Version and records:**
   - Bump to v0.10.0.
   - Add PHASE3 §3v (implementation; §3p–3r are main's CI/release entries).
   - Update PROGRESS.
   - Note in PLAN_V09 that its zoom conclusion holds only for the no-objective case.

## Not changed

- Edge path and art, dock, window, icon size, radar dots, mission givers (still unplayed), rotation.
- The objective tint.
