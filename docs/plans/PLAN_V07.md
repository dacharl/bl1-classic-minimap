# v0.7 plan: HUD integration (dock, skew, ECHO), marker cleanup, no-flicker rebuilds (2026-10-24)

Based on run 9 (v0.6.0: Arid, Skag Gully, T-Bone Junction/DLC3). **Implemented as v0.7.0** (PHASE3 §3l). Deviation from the plan: the window is sized to Enhanced's 220-unit width with our 820.75×527 mask aspect, so it is shorter than Enhanced's 220×180; use "Docked size" to adjust.

## What run 9 showed

**Working:**
- **Radar enemy dots:** F7 shows `threat_source: radar`, `radar_active: 1`.
- **Turn-in tint:** `tint: 16761888` is gold.
- **DLC3 map:** `dlcmap1`, frame 31, via InitMapFrame.

**Problems:**
1. **Stuck markers:** a white diamond and a green-outlined arrow that never move (Skag Gully, T-Bone).
2. **Flicker:** the map blinks on every objective or mission rebuild (TK's Food).
3. **Overlap:** the minimap covers ECHO comms, the Angel video and the top of the mission text.

## 1. Stuck markers: hidden source clips (cause found)

- **Evidence:**
  - `tools/swftimeline.py dist/phase2/HUD_minimap.gfx 1132` shows that the `maps` sprite places its icon **source clips** on frame 2 (`landmarks` char 1066 at depth 6, `players` char 1080 at depth 9, both at (0, 0)). They are never removed, so they persist on every later zone frame.
  - Their first frames are `objective` (the landmark sprite's labels are `objective, rstation, poi, …`) and `player`.
  - `AddLandmark` duplicates them; the originals stay on stage at the `maps` origin, which is not a world position. In Arid that origin happened to fall out of the way; in Skag Gully and T-Bone it's inside the art.
  - The crop of your Skag Gully shot shows exactly that: a white diamond bottom-left and a second, green-outlined player arrow, next to our real (black) arrow.
- **How Enhanced handles it:** `Minimap.SetMapFrame(label)` (E_HUD, `evidence/E_HUD_Minimap_class.as`) does `maps.gotoAndStop(label)` and then `maps.players._visible = maps.landmarks._visible = maps.enemy._visible = false`. Its `AddLandmark` then sets `newObject._visible = frameVisible` on each duplicate, because duplicates inherit the hidden state.
- **Fix (movie):**
  - `MinimapClear` (run before every redraw) hides `map.maps.landmarks/players/enemy`.
  - The `add` command and `MinimapPlayer` set the new clip's `_visible = true`.
  - The test VM's `duplicateMovieClip` copies `_visible`, as Flash does, so the harness catches a missing re-show.

## 2. Flicker: the mod hides and clears the map on every rebuild (cause found)

- **Mechanism:**
  1. `rebuild()` → `S.reset()` (drops the movie, `phase = idle`, `shown = None`).
  2. The next tick sees a "new" movie → `start()`, which sets `map._visible = False` and runs `clear` (removes every icon).
  3. `collect()` → frame wait → `capture()` → visible again on the following tick.

  Run 9's log shows about 100 ms blank per rebuild (`14:47:46.022` rebuild → `.120` shown), and TK's Food rebuilds on each objective step.
- **How Enhanced handles it:** the HUD's `RebuildMinimapObjects` event clears and rebuilds the objects inside the same update, with no hide (ENHANCED_NATIVE.md §1).
- **Fix (mod):** rebuild in place.
  - Keep `S.movie`, the attached clip, the visibility state and the current marks.
  - Run `collect()` and `capture()` in the same tick. The zone frame is already on stage, so `frame_ready` is true unless the anchor or frame changed.
  - `place_static` swaps the icons in one pass.
  - Only a level change, a new HUD movie or a frame change goes through the full reset path.
  - The settle rule stays tied to level changes, as now.

## 3. HUD integration: dock like Enhanced, with its skew, and move ECHO out of the way

**How Enhanced does it** (E_HUD sprite 933 = the 16:9 single-player `p1` layout, read with `tools/swftimeline.py`):

| Element (child of `p1`) | Enhanced placement (sx, skew0, skew1, sy, tx, ty) | Classic placement (sprite 706) |
|---|---|---|
| `map` (minimap) | 0.698, **0.049**, 0, 0.700, 919.4, 73.4 | none (ours is `_root.map`) |
| `echo` (comms/video) | 0.998, 0.070, 0, 1.000, **610.0**, 13.1 | 0.998, 0.070, 0, 1.000, **791.5**, 37.1 |
| `quest` (mission title) | 0.998, 0.070, 0, 1.000, 577.0, 129.1 | 0.998, 0.070, 0, 1.000, 545.0, 171.1 |
| `check1..5` (objectives) | **0.918**, 0.064, 0, 0.920, 795.9, 59.4 + 16.4n | 0.998, 0.070, 0, 1.000, 747.2, 92.4 + 19.7n |

- **The skew is a shear in the placement matrix, not 3D.** Every right-column element has skew0 ≈ 0.070·sx (y grows by 7% of x, so the right edge sits lower); left-column elements have −0.070. `p1` itself is unskewed (root places it at (216.6, 35.5) in Enhanced and (216.1, 30.4) in classic). Both movies use SWF v9, and neither has 3D properties (`_xrotation`/`_yrotation`).
- **ECHO repositioning is per-player Flash code.**
  - Script: `WillowHUDGFxMovie.UpdateCompassMinimapVisibility` sets `p<N>.map._visible` from the profile, then calls `AS_UpdateEchoPosition(I, bMinimapVisible)`, which Invokes `p<N>.UpdateEchoPosition(bool)` (`evidence/out_E_hudmovie.txt`).
  - Flash, defined in each layout sprite: `echo._x = map._x − 309.4` when the minimap is on, otherwise `map._x − 81.4`.
  - The mission title and checklist don't move at runtime; Enhanced's layout simply authored them smaller and higher (table above).
- **Why classic overlaps:**
  - Classic's `echo` lands at stage ≈ (1008, 67); its panel is about 186×139 (background shape 213 at x −9..177, y −1..134).
  - Our map at 28% covers stage x 1008–1238, y 20–210. That's the ECHO panel and the Angel video exactly, plus the end of the quest title.
- **Classic can do the skew.** REA on the decoded classic exe:
  - `search_strings`/`xrefs`: `matrix`, `colorTransform` and `pixelBounds` are referenced from the Scaleform `Transform` getter/setter code (`0x17a5c40–0x17a6dba`; `0x17a6400` = `push "concatenatedMatrix"; call <name compare>`).
  - `transform` is referenced from MovieClip member code (`0x1687c6e`, `0x1687d14`) and a member table (`0x1d89818`).
  - The `Matrix` class has about 20 method sites (`0x17a74ef–0x17a85b9`); `flash.geom` is at `0x1771fca`.
  - So `MovieClip.transform.matrix = new flash.geom.Matrix(a, b, c, d, tx, ty)` is compiled in. This is static evidence; one in-game read-back confirms it (step 3c).

**Plan:**
- **3a. Docked layout (new default):** place `_root.map` so that, in `p1`'s space, it matches Enhanced's `map` placement.
  - Our clip's mask is 821×681 at (64, 72); Enhanced's window is 220×180 centred on its origin (its edge test is `|x| > 110 || |y| > 90`). So the local matrix is: scale k = 220/821 (≈ 0.268; the height comes out 182 vs 180), then Enhanced's (0.698, 0.049, 0, 0.700), then translate so the mask centre (474.5, 412.5) lands on (919.4, 73.4).
  - Then compose with `p1`'s matrix (read at runtime: `p1._x/_y/_xscale/_yscale`; the 4:3 layouts use `_xscale` 132) to get `_root` coordinates, and set it with `map.transform.matrix`.
  - A new AS function `MinimapDock(a, b, c, d, tx, ty)` takes the `p1`-space matrix. The mod sends the per-layout matrix, so resolution and layout changes need only a re-dock.
  - **Per-layout table:** extract Enhanced's `map/echo/quest/check` matrices for each `p1` layout sprite (933 16:9, 949 4:3, and the split-screen ones) at build time with `swftimeline.py`, and map classic's layout sprites to them by root frame label (`16_9_end`, `4_3_end`, …).
  - The mod reads `p1`'s current layout from the root's `_currentframe` label, or by testing which sprite `p1` is. v1 stays single-player `p1`.
- **3b. Move the HUD column while the minimap shows** (Enhanced's `UpdateEchoPosition`, extended to quest/check, which Enhanced authored rather than moved):
  - New AS function `MinimapHudShift(on)`. The first time, it records the original `_x/_y/_xscale/_yscale` of `p1.echo`, `p1.quest` and `p1.check1..5`.
  - When on, it applies Enhanced's placements (`echo` 610.0/13.1; `quest` 577.0/129.1; `check<n>` 795.9 / 59.4 + 16.4(n−1), scale 91.8/92%). When off, it restores the originals.
  - Their skew is already in their placement, and setting `_x/_y` keeps it. Don't touch `_rotation` on skewed clips (that recomposes the matrix and drops the skew in Flash).
  - The mod calls it from `set_visible` (shown → on, hidden → off), on disable/teardown (off), and after every re-dock.
- **3c. Fallback if `transform.matrix` doesn't take:**
  - `MinimapDock` reads back `map.transform.matrix.b` into `_root.mmDockB`; the mod compares it with what it sent and logs once.
  - If it didn't take, dock without skew (scale and position only, same rectangle), which still fixes the overlap.
  - Composing a shear from nested rotations is possible (any 2×2 = R·S·R) but needs a wrapper clip and path changes, so it's held back unless the read-back fails.
- **3d. Options:** "Position: Docked (Enhanced) / Custom". Custom keeps today's Size/Right/Top sliders, and the HUD shift still applies if the custom rectangle intersects the column. Docked ignores the sliders except a "Docked size" factor (default 100%).
- **3e. Assembler:** `new flash.geom.Matrix(...)` needs `NewMethod` (0x53) on `flash.geom`, which as2asm can't emit yet. Add `('newm', obj, method, *args)`, and add a `flash.geom.Matrix` / `transform` model to the test VM. The VM's display model doesn't need skew maths: the tests assert the matrix values sent, and that icon placement inside `maps` is unchanged.

## 4. Smaller items from the same research

- **Rebuild trigger:** Enhanced rebuilds only on `MarkMinimapDirty` (mission/interactive-object setters). Ours polls the key every 0.5 s, which is fine once rebuilds are in place (§2).
- **Co-op buddy markers:** still skipped (WPRI records). Enhanced projects `PRI` replicated locations per tick. That's a later item.

## 5. Tests to add (offline, before install)

- **Corner markers:** the `maps` source clips are hidden after a zone frame change and after every redraw; every created icon (landmarks, player) is visible; the VM's duplicate copies `_visible`, so a missing re-show fails.
- **No-flicker rebuild:** an objective move or mission change doesn't set `map._visible` to false, doesn't reset `S.movie`/phase, swaps the icons in one tick, and never leaves an empty `maps` between ticks. A level change still takes the full path.
- **Dock:** `MinimapDock` receives the composed matrix for the 16:9 and 4:3 `p1` placements; read-back mismatch → unskewed fallback, logged once.
- **HUD shift:** `echo/quest/check1..5` move to the Enhanced placements while shown; tunnel, menu, death and disable restore the exact originals; repeated toggles don't drift.
- **Unchanged:** all v0.6 scenarios (radar, tint, Step B transform) stay green.

## 6. In-game checks (run 10)

1. In Skag Gully and T-Bone: no stray diamond or arrow.
2. Docked map at the top-right with the same tilt as the ammo and mission text; ECHO and the Angel video appear left of it; mission title and checklist readable.
3. TK's Food (multi-step): no blink when objectives advance.
4. F7: `dock_b` matches what was sent (0.049·k-scaled), or the log says the unskewed fallback is in use.
