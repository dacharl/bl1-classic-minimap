# Plan: drive the Flash minimap directly, use the helper at most transiently

## Why (run 6, v0.3.0)

Two screenshots: the minimap window is on screen, it's blank until the full map has been opened once, and then it shows the whole zone, unzoomed. `unrealsdk.log`:
- `map attached` at 01:38:35 (spawn): blank;
- `map attached` at 01:39:08 (rebuild after closing the status menu): art.

**Cause:**
- The first helper initialised before the zone's `LevelLandmarkAnchor` had streamed in. Native frame init "requires an anchor and nonempty frame label" (steam-deck-scripts phase-3 research), so `maps` stayed on frame `none`.
- The `none` frame's `themap` is a plain dark shape, which the readiness check (`themap._width` finite) accepted.
- The zoom after the later init was also wrong. Driving the native helper every tick (`UpdateObjects` + `ApplyFlash`, with its clamped panning and dirty-marker logic) leaves us dependent on state we can't see.

The prior work avoided the helper because the game GCs helpers after about 60 s. We fixed that with `KEEP_ALIVE`, but the prior research also maps out direct paths that make the per-tick helper unnecessary.

## What the native helper does that Python can do itself

| Native step | Direct replacement | Evidence |
|---|---|---|
| Pick the zone frame (`InitMapFrame` → `map.maps.gotoAndStop(label)` or `InitDLC`) | Read the label once from the helper (`map.maps._currentframe` after a successful `InitMapFrame`); later, read it from the anchor | phase-3 research; PHASE0 2d |
| `Transform` = inverse of the anchor's forward matrix (translation, orientation, scaled texture extents) | **A:** copy it from a transient helper. **B:** build it from anchor fields | Fyrestone: anchor → q = (0, 0); extents ≈ 59,597 × 119,363 = texture 512 × 1024 × ~116.5, axes swapped. The scale source field is unknown |
| `CoordScale` aspect correction | `CoordScale.Y = (ClipW/ClipH)/(AnchorW/AnchorH)`, `X = 1` | PHASE0 2d (exact) |
| Landmark list (`FindLandmarks`/`FindObjects`) | Copy actor + clip frame once from the transient helper's `MapObjects`. Positions are static, projected in Python | PHASE0 logs |
| Player marker (`FindPlayers`/`UpdateObjects`) | `pc.Pawn.Location` / `Rotation.Yaw × 360/65536` each tick | PHASE0, classic-decision |
| Objectives (eight waypoint slots) | `MissionTracker.ActiveMission` waypoints now; later `WillowGameReplicationInfo.ActiveWaypointData[8]` (possible, layout-backed) | classic-decision, Objective Distance |
| Centring / zoom (`ApplyFlash`, `ApplyScale`) | Our own `MinimapRecenter` + `SetMapScale` with a fixed zoom: no clamp, no `DesiredCenter` | PHASE2 functions |

## Step A (now): transient helper, then Python owns everything

1. **Wait for the anchor.** On a new HUD or a mission/area change, construct a helper (`KEEP_ALIVE`) and call `Init(pc)`. **If `helper.Anchor` is `None`, release it and retry in 1 s.**
2. `InitMapFrame` → require `map.maps._currentframe > 1` (not `none`), plus `InitMapFrameVars` (or the polled DLC movie load).
3. **Copy primitives:** frame, `Transform` (16 floats), `CoordScale`, `AnchorSize`, `ClipSize`, and the landmark list (`actor path`, `clip`, `frame`, world location). Call `SetMapScale(zoom)` ourselves and re-read the art size. **Release the helper** (clear `KEEP_ALIVE`). It lives for a few ticks at most.
4. **Each tick (20 Hz):** project the pawn with the copied transform; `MinimapCmd("player~u~v~deg")` → place the player icon and recentre/rotate. Landmarks are added once (`add~clip~u~v~angle~frame`). Objectives and threats are refreshed on their own timers.
5. **Each init:** log the anchor's reflected fields (`DrawScale`, `DrawScale3D`, `Rotation`, `TextureSizeX/Y`, label-like strings) next to the helper's `Transform`. That's the data Step B needs.

New AS commands: `player`, `add`, `frame`, `scale`. The existing `MinimapRecenter`, `UpdateThreats` and `MinimapClear` are reused.

**Also:**
- Make the readiness check reject frame `none`.
- Re-check the default position: it currently overlaps the tracked-mission text, so lower or shrink it.

## Step A: implemented (v0.4.0, 2026-10-24)

**Mod** (`sdk_mods/classic_minimap`):
- **Phases:** `retry` (attach) → `anchorwait` → `framewait` → `running`.
- **Anchor wait:** construct the helper with `KEEP_ALIVE` and call `Init`. If `Anchor` is `None`, release it and retry after 1 s, or 5 s after ten attempts. The map stays hidden (`map._visible = false`) meanwhile.
- **Frame wait:** `InitMapFrame`, then wait for `map.maps._currentframe > 1` and a finite art width (5 s timeout → release → retry).
- **Capture:** `InitMapFrameVars` + `UpdateObjects(true)`. Copy `Transform` (16 floats), `CoordScale`, frame and every non-player object's `(AS_IconClipPath, AS_IconClipFrame, TransformedLocation, Angle)`. Then **release the helper**. `MinimapClear` removes the icons the native pushed, then `scale~<zoom>` and one `add~…` per landmark.
- **Each tick:** the pawn is projected with the copied matrix → `tick~u~v~deg~rotate~offset`. No native helper call.
- **Threats:** same projection. Zoom or size changes re-place the landmarks.
- **Rebuilds:** a mission or area change, F8, or closing the status menu re-runs the whole sequence.
- **Window position:** default top margin is now 20, so the window sits above the tracked-mission text.

**Step B data:** each capture appends `{anchor, level, frame, Transform, CoordScale, AnchorSize, ClipSize, ViewSize, markers, fields}` to `sdk_mods/settings/classic_minimap_anchors.jsonl`. `fields` is every primitive, struct, name and object property of the anchor's class (reflected through `Class._fields()` / `_get_field`), capped at 400.

**Movie:** `MinimapCmd` gains `tick`, `add`, `frame` and `scale`, plus the root function `MinimapPlayer(u, v, deg)`. Package `GfxHUD_Minimap.upk`: SHA-256 `19282138…724a`.

**Tests:** the interpreter suite covers the new ops (frame, scale, player create/move/turn with centring and rotation, add, unknown command). The mod integration suite covers anchor missing → hidden + retry, anchor arriving → framewait with the helper pinned, capture → helper released with the matrix/scale/markers copied, native icons replaced by ours at the right positions, the anchor record written, per-tick player drawn from the pawn with zero helper calls, a zoom change re-placing landmarks, a frame stuck on `none` → timeout + release + retry, and all earlier scenarios. Everything passes.

## Step B (after one Step-A run): no helper at all

Fit the anchor-field → `Transform` formula from the logged pairs (at least two zones), plus the frame label from the anchor. Then initialisation needs no native helper, no menu and no GC handling.

## Tests

- Extend the offline interpreter and mod harness: anchor missing → retry; frame `none` → not ready; transient helper released after copying; pawn → player icon at the mask centre, rotated; fixed zoom applied; landmarks placed once.
- All existing scenarios stay green.
