# Prior research (steam-deck-scripts) and this mod

Source: `C:\Users\Charles\Dev\steam-deck-scripts`. This covers the BL1 specs under `docs/superpowers/specs/2026-10-1*-bl1-*`, the research under `docs/research/2026-10-1*-bl1-*`, and the `BL1MinimapPOC` / `BL1MapDiagnostics` SDK mods under `scripts/games/borderlands-1-goty-classic/`. That work statically analysed the **decrypted** classic executable (Ghidra 12.1.4, x86) and ran a Canvas-based minimap POC on the Deck.

## What it confirms

| Prior finding | Where | This repo |
|---|---|---|
| Classic natives: `InitMapFrame` (anchor/label frame or DLC), `InitMapFrameVars` (terrain + mask sizes, aspect correction), `UpdateObjects` (existing records, live player/waypoint projection, **no removal**), `FindPlayers`/`FindObjects` (**append**), `ApplyFlash` (movie/dirty markers, **clamped panning**); no `FindWaypoint`, no minimap subclass | classic-decision.md | Matches REPORT §1.4/§2 (exec table, strings) and PHASE0 §2d (clamp seen at both edges) |
| Projection `((qY+.5)*sx, (.5−qX)*sy)` after the world→anchor transform | classic-decision.md | Same as PHASE0 §2d: `tr.x = (v+0.5)·CoordScale.X`, `tr.y = (0.5−u)·CoordScale.Y`; used for threat dots |
| Yaw → degrees `360/65536` | classic-decision.md | PHASE0: `Angle` = yaw in degrees |
| The status menu creates and owns the helper; there's no HUD minimap owner in classic | classic-decision.md | REPORT §2 |
| **Helper lifetime / GC is unresolved**; the Deck trial logged "two missing transient helpers (`WillowGFxHelperMap_0` and `_2`)" | runtime-followup.md, classic-decision.md | Hit as the v0.2.0/v0.2.1 GPF in `pyunrealsdk.dll` on an attribute read (PHASE3 §3f). Fixed with `ObjectFlags.KEEP_ALIVE` (v0.2.2) |
| `FindObjects` only appends; `UpdateObjects` rereads eight waypoint slots by ordinal and skips zero slots without clearing, so **objective markers go stale** after mission changes | classic-decision.md | v0.3.0 rebuilds with a **fresh helper** (no append on an old one) when the tracked mission or visible levels change |
| Objective Distance re-finds helpers with `find_all`, skips `bDeleteMe`/`bPendingDelete`/other owners, calls `FindObjects()`, and caches by mission + target/turn-in definitions + visible levels | runtime-followup.md → its source | v0.3.0 uses the same cache key: `MissionTracker.ActiveMission`, `TargetWaypointDefinition`, `TurnInWaypointDefinition`, visible `StreamingLevels` |

## Where this mod knowingly differs from the prior decision

The prior decision chose a Canvas renderer fed by copied snapshots, and it explicitly decided against *creating helpers, holding native references, or calling `InitMapFrame`/`ApplyFlash` against an off-menu movie* ("no established safety advantage"). This repo does all three, for these reasons:

- **Off-menu movie:** this isn't the stock HUD. It's `GfxHUD_Minimap.FlashMovie.HUD`, which carries the status menu's own `map` clip tree (`mask`, `maps` with every zone frame, the icon clips) and root `AddLandmark`/`UpdateLandmark`/`SetMapScale`/`InitDLC`. Those are the exact paths the classic natives write to (REPORT §2, PHASE2). The Phase 0 probe ran `InitMapFrame`/`InitMapFrameVars`/`UpdateObjects` against a HUD movie without a crash, and v0.2.0 attached the map in game.
- **Holding the helper:** it's constructed with `KEEP_ALIVE` and released on every reset, rather than left to the GC. Nothing else native is held between ticks: the HUD movie is a `WeakPointer`, objective keys are strings of freshly read objects, and the mission tracker is a `WeakPointer`.
- **Rendering:** Scaleform draws the map, using the full map's own vector art, icon frames and DLC loader, instead of a Canvas wireframe. The trade-off is that it depends on the patched movie package.

## Still unresolved (from both efforts)

- That `KEEP_ALIVE` really prevents collection on classic under load and level travel. The value comes from `mods_base` (`0x4000` for Willow), not yet confirmed in game.
- Freshness of the eight waypoint slots between rebuilds, and sparse or zero targets. The rebuild key covers mission and area changes, not changes in target position within one mission.
- Frame cost of `UpdateObjects(false)` + `ApplyFlash` at 20 Hz on the Deck.
- Co-op and split-screen. v1 targets player 1 only.
- Threat selection. This mod uses `Pawn.IsEnemy` + `IsAliveAndWell` + range + the AI rule engine's `IsPawnShownInRadarForCurrentState`; the prior work left threats out of scope.

## Possible next steps drawn from the prior work

- **Waypoint-slot freshness:** a read-only sampler for `WillowGameReplicationInfo.ActiveWaypointData[8].WaypointLocation/WaypointRadius` (prior status: *possible, layout-backed*), adding slot changes to the rebuild key.
- **Diagnostics:** reuse the BL1MapDiagnostics / lifecycle-capture pattern (bounded events, automatic checkpoints, a fixed-name report in `sdk_mods/settings`) for Deck trials without a keyboard. The Deck has no F7.
