# v0.9 plan: Enhanced's minimap box and window (2026-10-24)

**Implemented as v0.9.0** (PHASE3 §3t).

**Zoom correction after run 13:** the fixed-108% conclusion below applies only without objectives.
`extInitComplete` also calls native `QuickAccessInit`, which fits the player and objectives before the +8 step.
See PLAN_V10 for the recorded native evidence and v0.10 implementation; the box/window research remains valid.

Run 12 confirmed v0.8's zoom, icons, tilt and north marker. Enhanced footage still looks different: a framed box with a dark background and a taller view. This plan reproduces Enhanced's minimap clip itself instead of approximating it with classic's status-menu mask.

## Research (evidence)

### The box: Enhanced minimap clip, E_HUD sprite 187

Read with `tools/swftimeline.py` and a direct tag scan (the GFx gradient-image IDs collide with character IDs in `swfdeps.Movie.defs`, so those were checked directly).

| Depth | Char | Name | What it is |
|---|---|---|---|
| 3 | 81 | (none) | **Box art**: vector Shape3, 263.4 × 238.5, centred (x −130.75..132.65, y −117.9..120.6), no bitmaps. Behind the map: background plus border. |
| 4 | 83 | `mask` | **Window**: one-frame sprite holding shape 82, **207.95 × 173.65 centred** (x −103.95..104, y −86.8..86.85). Placed with **clip depth** (flags 0x66), so it masks the map art below it. |
| 6 | 178 | `maps` | Zone art plus `landmarks`/`players`/`enemy` (same art and placements as classic's 1132) |
| 19/21/23 | 182/184/186 | `northMC`, `customWaypointMC`, `currentObjectiveMC` | Edge indicators at (0, −55); their path is the rectangle **±110 × ±92**, just outside the window, on the box border |

### Zoom

- **Script is the only source** (`tools/uedis.py E`): `WillowHUDGFxMovie.extInitComplete` sets `CurrentScaleIdx = 3` → `ApplyScale` → `SetMapScale(Scales[3] = 100)`, then `AnalogScale(1.0)` → `FClamp(100 + 1.0 × ZoomSpeedFactor 8)` = **108**.
- **`WillowGFxHelperMinimap` overrides `ApplyScale`/`ApplyAnalogScale`**, but only to read `ClipSize` back through `Invoke("GetMapWidth"/"GetMapHeight")`; the scale value is unchanged. The other callers (`StatusMenuExGFxMovie`, `CycleScale`) belong to the full map.
- **Flash passes it through:** the root `SetMapScale(scale)` calls `p<N>.map.SetMapScale(scale)` unchanged, and `Minimap.SetMapScale` sets `maps.themap._xscale/_yscale = scale`. Root `GetMapWidth` returns `p<N>.map.maps.themap._width`.
- **No native code sets it:** the decoded Enhanced exe contains no `SetMapScale` string in ASCII or UTF-16 (scratchpad `strrefs.py`).
- **The art matches:** E sprites 87 and 138 place their shapes at identity, the same as classic's 1046 and 1118, and the shapes are the same size.

**Conclusion:**
- **Zoom:** Enhanced's zoom is a fixed 108% in its clip's units, and v0.8 (403% relative to a 220-unit window) already gives the same scale.
- **Window:** v0.8 shows **220 × 141** units (classic's 820.75 × 527 status-menu mask scaled to 220 wide). Enhanced shows **207.95 × 173.65**, about 23% more height, and draws the box art behind the map.

## Plan

1. **Movie (`swfbuild.py`):**
   - Build `bl1mm_map` like E 187:
     - copy shape 81 (box) and shape 82 (window) as new ids;
     - wrap the window in a sprite that places it at (+103.95, +86.8), so the mask clip's `_x/_y` is its top-left corner, as the mod's centring and edge maths expect;
     - place the box at depth 3, the window at depth 4 named `mask` with clip depth 6, and classic's `maps` (1132) at depth 6.
   - Classic's status-menu mask (1040) is no longer used.
   - **Edge path:** like Enhanced, the indicators sit on the box border at ±(half window + 6, half window + 5.15), i.e. ±110 × ±92, rather than inset inside the window. The icon/diamond handoff (run 12) is unchanged.
2. **Mod:**
   - **Window geometry** becomes Enhanced's (`MASK_LEFT/TOP/W/H` = −103.95, −86.8, 207.95, 173.65).
   - **Docked:** Enhanced's `p1` matrix as is (k = Docked size only), composed with `p1`.
   - **Zoom:** `themap` = 108% × the zoom option.
   - **Icons:** the icon size option only (100% = Enhanced; no 3.73× compensation).
   - **Custom position** keeps the old meaning (window width = 820.75 px × Size%) with the new geometry.
3. **Tests:**
   - The VM map clip mirrors the new structure (box, top-left-anchored 207.95 × 173.65 mask, maps).
   - The AS suite checks the box/mask/clip-depth structure in the built movie, edge positions on ±110 × ±92, and the handoff.
   - The mod suite checks the dock matrix (Enhanced's own), zoom 108, icon scale 100, and the custom placement.
4. **Build, install, docs:** PHASE3 §3t, PROGRESS, commit on the worktree branch.

## Not changed

- Rotation behaviour, mission givers (not yet verified in game), radar dots, the HUD column shift (its positions are Enhanced's, made for this box).
