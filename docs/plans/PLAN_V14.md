# v0.14 plan: tuning before 1.0 (2026-10-26)

**Zoom mode implemented offline as v0.14.0 (PHASE3 §3am); the other tuning items are still to research.** PLAN_V13 decision 20 put tuning here, and decision 21 made it part of the 1.0.0 release
gate. This first section covers the zoom on mission switching (run 22 follow-up); the other tuning items are listed
at the end and are still to be researched.

## Research (evidence)

### Zoom on mission switching

The user saw the zoom change when switching the tracked mission: out when the new waypoint leads to another map, in
when it is in the same map. Details are in PHASE3 §3al.
- **Enhanced script** (`uedis.py E`):
  - `WillowHUDGFxMovie.extInitComplete`, which runs when the HUD movie initialises (level load), is the HUD's only
    fit: `QuickAccessInit()`, then `AnalogScale(self, 1.0)`;
  - `RebuildMinimapObjects`, its objective-change event, rebuilds markers only, with no scale call.
- **Enhanced native (REA, evidence `ev_ccef4228…`):** `QuickAccessInit` (`0x14139a970`) has no direct callers.
  Its only references look like vtable slots, and any virtual calls to it are unresolved.
- **Enhanced:** the zoom chosen at a level load stays until the next one.
- **Ours:** `on_status_menu_close` → `rebuild()` → `rebuild_pending` clears `fit_anchor` and refits. Missions are
  switched in the status menu, so every switch refits. This dates from v0.10's "explicit rebuilds refit".

### Zone scales (for the post-1.0 fixed mode)

World metres across the map window at 100% zoom, from the recorded anchors (scratchpad `zonescale.py`; `fit_zoom`'s
maths, assuming each record's `ClipSize` is the art at 100%):

| Zone | Art (px) | UU per art px | Window width at 100% |
|---|---|---|---|
| DLC2 lobby | 468 × 503 | 14.3 | 59 m |
| Dry | 536 × 510 | 65.6 | 273 m |
| DLC4 Tartarus Station | 513 × 513 | 75.8 | 315 m |
| DLC1 island | 479 × 496 | 78.4 | 326 m |
| Skag Gully | 281 × 519 | 83.0 | 345 m |
| Arid Badlands | 780 × 352 | 153.1 | 637 m |
| DLC3 hub | 250 × 500 | 200.6 | 834 m |

A fixed percentage therefore shows anywhere from 59 m to 834 m: a 14× spread. A "fixed" mode would choose the zoom
per zone so that the window always covers the same number of metres.

### Vehicles (for post 1.0)

- Classic's own status menu tests `WPCOwner.Pawn.IsA('Vehicle')`: while you drive, the controller possesses the
  vehicle (`WillowPlayerController.Possess(aPawn, bVehicleTransition)`).
- Enhanced's HUD script has no vehicle zoom.

## Scope

- **For 1.0:** a zoom-mode option with two modes. **Enhanced** fits once per HUD (level load), plus F8. **Objective**
  also refits when the tracked mission changes, which is the current behaviour. The option is built so a third mode
  can be added later.
- **Post 1.0 (user, 2026-10-26):**
  - a **Fixed** mode: the same metres across the window in every zone (the table above);
  - a **vehicle zoom:** zoom out 2–3× while driving, and restore the previous zoom on exit.

## Run 23 findings (PHASE3 §3an)

- **Icons rotate with the map in "Rotate with player".** Enhanced counter-rotates every landmark icon and every
  threat (`CancelOutIconRotation`); ours does only the threats. Fix: counter-rotate every dynamic icon except the
  player, in `MinimapRecenter`.
- **Angel's video is half hidden behind the map.** It is a 3D hologram: `PlayVoGEchoCall` renders
  `VoGEchoCallGFxMovie` onto `GFxUIManager.ScreenMesh`, attached to a camera actor, so the HUD always draws over it
  and depth can't fix it. Enhanced places it per screen layout from four `GlobalsDefinition` `Vector4` values that
  classic lacks (single player: (−2.1, −0.4, 0.14, 0.0)); classic's native placement is fixed (top right). Options:
  - move the mesh to Enhanced's single-player placement when a call starts (an in-game spike on `ScreenMesh`'s
    translation: log classic's own values first, then apply Enhanced's);
  - hide the minimap while a call plays (hook `PlayVoGEchoCall`, end on `StopEchoCall` or the movie closing).
- **The autosave indicator covers the minimap.** `WillowHUD` draws `SavingIndicator_INST` natively on the canvas,
  above all GFx. Script natives bracket a save: `NotifySavingStarted` and `NotifySavingComplete(InSaveDuration)`.
  Hiding the minimap was considered and **rejected by the user** (2026-10-26); the item stays open.

**v0.14.1 (PHASE3 §3an):** the counter-rotation fix, plus the Angel spike: each call logs the mesh, and "Angel
position (experiment)" = Enhanced applies `(-2.1, -0.4, 0.14)`, re-applying it if the native code moves it back.

## Other tuning items (from PROGRESS, not yet researched)

- The level-change-to-minimap delay (about 10 s: anchor wait plus the 3 s settle).
- The zoom with no nearby objective, compared with Enhanced's `QuickAccessInit` (Skag Gully at the 108% floor).
- The threat marker's size compared with Enhanced.
- The merge cost, re-measured with the movie cache (v0.13 removed one 0.7 s read).
- Never-confirmed checks (1.0 gate): the single edge diamond, "Rotate with player", and the edge clamp near art
  borders.

## Decisions (grilling round 1, 2026-10-26, all accepted)

1. **One "Zoom mode" spinner: Enhanced (default) and Objective.** "Fixed" joins it after 1.0, so there's no
   settings migration.
2. **Objective mode refits when the tracked mission or its status changes**, wherever that happens: a switch in the
   status menu, a turn-in, a newly tracked mission. A waypoint moving within the same mission doesn't refit.
   Enhanced mode keeps the HUD's fit until the next level load, and closing the status menu rebuilds the markers
   only (as `RebuildMinimapObjects` does).
3. **F8 and the markers button refit in both modes.**
4. **The "Zoom (vs Enhanced)" multiplier applies on top of either mode.**
5. **Implemented now as v0.14.0;** the rest of PLAN_V14 is researched afterwards.
6. **Clearer button names (user):** "Rebuild now" becomes **"Refresh map markers"** (the F8 action), and "Rebuild
   HUD movie" becomes **"Rebuild HUD movie from game files"**. Buttons aren't saved in settings, so renaming is
   free. The F8 keybind keeps its identifier, so existing bindings survive.
