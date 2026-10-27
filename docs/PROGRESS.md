# Classic Minimap: progress (updated 2026-10-25)

An Enhanced-style minimap for **Borderlands GOTY classic** (Steam app 8980, x86, v1.5.0.0), using the willow1 PythonSDK plus a separately shipped HUD movie package.

This page tracks where the project stands: what works, what's installed, how to build and test, and what's left. Agents start at [AGENTS.md](../AGENTS.md) and players read the [README](../README.md). Keep this page current: update the milestones, "Installed right now" and "Open items" with every release and in-game run. The details of each run go in [PHASE3](log/PHASE3.md).

## Where it stands

- **v0.14.7 + profiler 0.1.13 (installed on the PC 2026-10-26 23:46 UTC, played in run 31; PHASE3 §3au, §3av):** "Angel position" (Classic / Centered, default Centered) moves Angel's ECHO video to the top centre, clear of the minimap; the shift is tuned to 0.28 of the overlay's width. Watch lines log the FOV and distance/scale for the invariance checks.
- **v0.14.6 + profiler 0.1.12 (installed on the PC 2026-10-26 23:08 UTC, played in run 30; PHASE3 §3at):** "Angel position (experiment)" = Enhanced (the user's current setting) shifts Angel's VoG overlay left by a quarter of its width, aiming for Enhanced's top centre.
- **v0.14.5 + profiler 0.1.11 (installed on the PC 2026-10-26 22:56 UTC, played in run 29; PHASE3 §3as):** run 28 showed Angel's particle sits at screen centre on the view axis with no start offset, so her top-right placement must come from the material. v0.14.5 dumps the particle's materials (per-call instance and template, parameters, parent chain).
- **v0.14.4 + profiler 0.1.10 (installed on the PC 2026-10-26 22:45 UTC, played in run 28; PHASE3 §3ar):** "Angel position (experiment)" = Enhanced centres Angel's VoG particle by zeroing its sideways start offset before the effect starts (the user's option is still Classic).
- **v0.14.3 + profiler 0.1.9 (installed on the PC 2026-10-26 22:35 UTC, played in run 27; PHASE3 §3aq):** run 26 showed Angel's video is a screen particle drawn under the whole HUD, not the ECHO panel or the root `vog` clip. v0.14.3 logs the particle's template, component and emitters at her next call.
- **v0.14.2 + profiler 0.1.8 (installed on the PC 2026-10-26 11:21 UTC, played in run 26; PHASE3 §3ao, §3ap):** run 25 (Deck) showed the game resetting the ECHO panel behind the map while the shift was on. The movie now re-applies the shift every frame (`onEnterFrame`, unverified on this runtime) and every tick, logs each re-apply, and F7 shows `hud_fixes`. Angel diagnostic: F7 and a watch log the HUD root `vog` clip; ECHO-call hooks.
- **v0.14.1 + profiler 0.1.7 (installed on the PC 2026-10-26 02:56 UTC, played in runs 24 (PC) and 25 (Deck); PHASE3 §3an, §3ap):** run 23 played v0.14.0, and the Objective zoom works. Fixes: every map icon stays upright in "Rotate with player" (Enhanced's `CancelOutIconRotation`). Spike: Angel's video is a 3D screen mesh that the HUD always covers; each call logs its placement, and "Angel position (experiment)" = Enhanced tries Enhanced's single-player placement. **Open (user):** the native autosave icon covers the minimap; no change for now.
- **v0.14.0 + profiler 0.1.6 (PLAN_V14 zoom mode, installed on the PC 2026-10-26 01:30 UTC, played in run 23; PHASE3 §3am):** the zoom changed on mission switches because closing the status menu refitted. Enhanced fits only once per HUD (script plus REA, PHASE3 §3al). New "Zoom mode": Enhanced (default, keeps the HUD's fit) or Objective (refits on a new tracked mission or status); F8 refits in both. The buttons are renamed "Refresh map markers" and "Rebuild HUD movie from game files". Fixed zoom and the vehicle zoom are post-1.0 (PLAN_V14).
- **Run 22 (v0.13.1 on the PC, PHASE3 §3al):** one green "X" at a ready turn-in (original art), then the gold "!" for the next mission, the tight box, and Enhanced's art after switching. The builds took 1.95–2.16 s, the Extended UI merge worked, and there were no errors. Still to see: Enhanced's turn-in mark at a ready objective, "Tint objective diamonds", and the Deck.
- **v0.13.1 + profiler 0.1.5 (installed on the PC 2026-10-25 23:56 UTC, played in run 22; PHASE3 §3ak):** run 21 played v0.13.0 on the PC with both art variants and Extended UI. The build took 1.84–1.92 s, the glyphs render, and the merge works. Fixes: objectives use Enhanced's turn-in and "!" marks (with "Tint objective diamonds" as an option for the old gold/green diamonds), one mark where a giver stands on the objective, a green "X" and a tight box in the original art, a cache slot per art choice, and the old-package note once.

- **One-file install (PLAN_V13, v0.13.0 + profiler 0.1.4, built and tested offline 2026-10-25, installed on the PC 23:06 UTC, played in run 21):** the mod builds its HUD movie on enable from the player's own `GfxHUD.upk` and `menus_ingame_redux.upk`, plus Enhanced's `GfxHUD.upk` when found, and caches it under `sdk_mods/settings/`; there is no `GfxHUD_Minimap.upk` any more. Without Enhanced it uses original art: game-font glyphs "X", "!", "N" and our own box, window and diamond. The in-mod build from the real installed files matches the tested movies byte for byte for both art variants. The release bundle is the `.sdkmod` files only. Next: in-game runs on the PC and the Deck (both art variants, plus Extended UI), then PLAN_V14 tuning, then the 1.0.0 public release. PHASE3 §3aj.

- **Runtime HUD merge (PLAN_V12, v0.12.0 + profiler 0.1.3, installed and played on the PC and the Steam Deck 2026-10-25, with and without Extended UI: works; the merge costs 3.4 s (PC) / 4.4 s (Deck) once per session):** `swfmerge.py` splices our block into another mod's HUD movie (Extended UI) when it takes the template, with status in the log, console and MODS menu; a refused movie keeps its template. The PC spike (run 18), the PC run (run 19) and the Deck run (run 20) all passed. PHASE3 §3ai.

- **Release and diagnostic tooling (2026-10-25):** `bump_version.py`, `release.py`, `install.py` and `diag.py` implement FRICTION's first three suggestions. CLI scenarios use temporary repositories/logs/game folders. A release built from the local game inputs passes both movie suites; no real installation or runtime version bump was performed. See [TOOLS.md](TOOLS.md), PLAN_RELEASE_TOOLS and PHASE3 §3ah.

- **Profiler add-on 0.1.0 (PLAN_V11, built offline, not installed):** `sdk_mods/classic_minimap_profiler/` attaches reversible wrappers to the core only during a capture, saves schema-v1 reports with an 8-slot archive, and leaves the core artifact byte-identical. The report contract is frozen (PERF_REPORT_V1 + fixtures, handoff H0 done); `steam-deck-scripts` owns the adapter (H1). Memory requirement met; the 0.05 ms p95 requirement is unresolved on the stub harness (wrapper cost ≈ 0.020 ms per admitted update). PHASE3 §3z.
- **Automatic test workers (2026-10-24):** task branch `test/auto-parallel-workers` adds CPU-based defaults for unit and mutation tests, independent unit processes with merged coverage, and clean mutation-worker shutdown on Python 3.13. CI and local commands use the same defaults; see CI.md and PHASE3 §3s. No runtime or installed files change.
- **Feature worktree rebase:** v0.10/F7 work is rebased onto main `6f840a6`; both real-movie suites, all 11 automatic unit cases, coverage/mutation gates and lint pass. All 2,898 mutations complete without errors, timeouts or cleanup warnings (PHASE3 §3x).

- **Works in game (confirmed through run 12):** zone art, landmarks, player centring, radar enemy dots, the objective turn-in tint, the Enhanced-style dock with the HUD tilt, ECHO/mission text moved aside, no-flicker rebuilds, DLC3 maps, Enhanced zoom and icon size, the north marker, and hiding during the tunnel, menus and death.
- **Run 13 (v0.9.0):** box size matches the footage, but the map is ~2.5–3× less zoomed and objectives near the top edge are clipped (PHASE3 §3u).
- **Run 14 (2026-10-24):** the profiler loads and captures in game. An objective near the window edge "wobbled" because the handoff measured the animated icon's live width; fixed in a rebuilt package (`5eefdf81…6d03`, installed; the previous `5bae8e3f…bc29` is in the worktree's `dist\v0100\`), mod unchanged (PHASE3 §3aa).
- **Run 17, Steam Deck (2026-10-24):** v0.10.2 works under Proton once **Extended UI** (Extended Item Cards 1.3.2) is disabled: it replaces the HUD movie with its own `GfxHUD_MOD` after our redirect, so only one can win. The map maths matches the PC exactly (PHASE3 §3ag). Compatibility and a clearer "another mod replaced the HUD" message are open.
- **Run 16 → v0.10.2, profiler 0.1.2 (installed, not yet played; previous files in the worktree's `dist\v0101-run16\`):** DLC maps confirmed fixed. The gold turn-in tint now multiplies instead of flattening (the diamond keeps its ring and centre), and the zoom fit is redone with the placed pawn the first time the map shows after a level change (PHASE3 §3af).
- **Previously installed (played in run 16):** mod v0.10.1, profiler 0.1.1, package `4a840f56…cabc`; previous files backed up in the worktree's `dist\v0100-run15\` (PHASE3 §3ad).
  - **Run 15 → v0.10.1:** a DLC-to-DLC trip on the same HUD (T-Bone → Tartarus) kept the old DLC map; fixed by leaving the `dlcmap1` frame when the DLC package changes. Profiler 0.1.1 accepts core 0.10.1 (PHASE3 §3ac).
  - **Threat markers:** Enhanced's red diamond with a black outline (E shape 127) instead of drawn squares, counter-rotated with the map (PHASE3 §3ad).
- **Gradient fix (installed; box confirmed faint blue in run 15):** the bright damage indicator and the green/red/white box came from the builder shifting classic's external gradient numbering; package `e2b687c1…ab51` restores it (PHASE3 §3ab).
- **Played in runs 14–15:** v0.10.0 plus profiler add-on 0.1.0 (PHASE3 §3z). v0.10.0 implements PLAN_V10's objective-fit zoom and switches to the edge diamond before an icon clips. Objective refreshes retain the fit; new anchors and explicit rebuilds refit. F7 reports the inputs and fitted/final zoom, and confirms the log write in the in-game console. Offline validation is recorded in PHASE3 §3v/3w.
- **Previously installed:** v0.9.0 (played in run 13), now backed up in the worktree's `dist\v090\`.
  - The map clip is now laid out like Enhanced's: its box art, and its 207.95 × 173.65 window instead of v0.8's squeezed 220 × 141.
  - Docking and icon size use Enhanced's own values; its fixed 108% zoom is corrected in v0.10 (PHASE3 §3t).
  - It includes v0.8.1's fixes: the edge diamond handoff, and the mission-giver calls ("!" and turn-in icons, still unplayed).
- **Earlier event:** run 11 crashed at startup because drive C: was full, not because of the mod (PHASE3 §3m).
- **Repository setup (2026-10-24):** Git initialized for a source-only initial commit; AGENTS now requires test-first behavior changes, Conventional Commits and no agent attribution. Build outputs and extracted game packages are ignored (PHASE3 §3o).
- **Release workflow (2026-10-24):** local branch renamed to `main`; manual GitHub Actions workflow packages the Python source as `.sdkmod` and publishes a version-tagged release. Hosted execution is pending; see README and PHASE3 §3p.
- **CI scope change (2026-10-24, user request):** only lint and unit tests with coverage run continuously and block; mutation testing moved to the on-demand `mutation.yml` workflow (PHASE3 §3z).
- **Source-only CI (2026-10-24):** lint, per-file line/branch coverage, all mod/packager mutants, workflow lint and repository/archive checks. Both existing suites pass against an asset-free fixture; hosted runs remain pending. See [CI.md](CI.md), PLAN_CI and PHASE3 §3q.
- **Worktree workflow (2026-10-24):** AGENTS requires a fresh worktree and a descriptive task branch for new coding tasks, with explicit user overrides for direct work on `main`. Branch names and worktree paths follow the no-attribution rule. CI/release setup was committed directly to `main` at the user's request (PHASE3 §3r).

## Milestones

| Version | What it delivered | In game |
|---|---|---|
| CI tooling | Automatic parallel unit/mutation workers with numeric overrides and combined unit coverage | Source-only; no installation |
| Maintenance tooling | Synchronized version/fixture edits, tested release bundles, verified installation/backups, log diagnostics | Offline and fake-install validation; no real installation (§3ah) |
| Phases 0–2 | SDK confirmed on classic (probe); `upkpatch.py` movie swap; `swfbuild.py` minimap movie | Probe runs 1–2 |
| v0.1–v0.2 | First mod; `SingleArgInvokeS` instead of `Invoke`; separate `GfxHUD_Minimap.upk` + template redirect | Runs 1–5: nothing shown, then GC crashes (§3b–3f) |
| v0.3–v0.4 | `KEEP_ALIVE` helper; objective refresh; transient helper gated on the zone anchor (Step A) | Run 6–7: working map (§3g–3h) |
| v0.5 | Visibility rules (tunnel, menus, HUD, death, 3 s settle); stale-objective key | Runs 7–8 (§3i–3j) |
| v0.6 | Transform computed in Python (Step B), radar enemy dots, objective status tint (from the Ghidra decomp) | Run 9: dots, tint and DLC3 confirmed (§3k) |
| v0.7 | Hidden icon templates, in-place rebuilds, Enhanced dock with the HUD tilt, ECHO/quest/check shift | Run 10: confirmed (§3l) |
| v0.8 | Enhanced zoom and icon size, north/objective edge indicators, "!"/turn-in mission givers | Run 11: disk-full crash (§3m). Run 12: zoom, icons, tilt and north confirmed; double marker and giver calls fixed in v0.8.1 (§3n) |
| v0.9 | Enhanced's box art and 207.95 × 173.65 window, dock/icon values, edge indicators on the box border | Run 13: box matches; fixed zoom and clipped icons need correction (§3u) |
| v0.10 | Native-style objective-fit zoom, full-icon edge handoff, F7 zoom diagnostics and console confirmation | Built; not installed or played (§3v/3w) |
| v0.12 | Runtime merge into other HUD mods' movies (`swfmerge.py`, block manifest), merge status messages | Runs 18–20: spike, PC and Deck with Extended UI work (§3ai) |
| v0.13 | Player-built movie: one-file install, movie cache, Enhanced discovery, original art, builder moved into the mod | Run 21 (PC): works with both arts and Extended UI (§3aj, §3ak) |
| v0.13.1 | Enhanced-style objective marks (tint option), one mark per spot, green "X", tight box, cache per art | Run 22 (PC): one turn-in mark, "!", tight box, art switch confirmed (§3ak, §3al) |
| v0.14.0 | Zoom mode (Enhanced: fit once per HUD; Objective: refit on mission change), clearer button names | Run 23 (PC): Objective zoom confirmed; rotation, autosave and Angel findings (§3am, §3an) |
| v0.14.1 | Upright icons when rotating; Angel position spike (log plus experimental Enhanced placement) | Run 24 (PC): the screen-mesh path never ran (§3an) |
| v0.14.2 | Re-applies the ECHO/quest/checklist shift whenever the game resets it, checked every frame and every tick (run 25, Deck); Angel diagnostic logging the HUD root `vog` clip | Run 26 (PC): no ECHO resets in a short session; Angel's video still behind the map (§3aq) |
| v0.14.3 | Diagnostic: logs Angel's screen particle (template, component, emitters) and its position against the camera | Run 27 (PC): dump captured; the particle sits on the camera's view axis (§3ar) |
| v0.14.4 | "Angel position (experiment)" = Enhanced centres Angel's VoG particle (zeroes its sideways start offset); lookup-table and rotation logging | Run 28 (PC): no start offset to remove; the experiment is a no-op (§3as) |
| v0.14.5 | Diagnostic: dumps Angel's particle materials (per-call instance and template, parameters, parents) and size table | Run 29 (PC): no position parameter; the overlay is 17.76 × 10, centred on the view (§3at) |
| v0.14.6 | "Angel position (experiment)" = Enhanced shifts Angel's VoG overlay left by a quarter of its width (top centre, like Enhanced) | Run 30 (PC): worked, Angel top centre and clear of the map (≈ 53% across) (§3au) |
| v0.14.7 | "Angel position": Classic / Centered, default Centered, shift tuned to 0.28; mesh spike move retired; FOV and distance/scale in the watch lines | Run 31 (PC): Angel centred (≈ 52%), stable between iron sights (FOV 48–53) and normal (70) (§3av); run 32 (Deck): successful at FOV 100 (§3aw) |
| v0.11 | Separate optional profiler add-on 0.1.0, telemetry-free core artifact, frozen report contract, overhead benchmark | Built offline; not installed (§3z). Adapter in `steam-deck-scripts` pending |

## Doc map

Docs are cited across the code and docs by bare name (e.g. "PHASE3 §3l", "PLAN_V08 3"); every name below is unique.

| Doc | What's in it |
|---|---|
| **research/** | |
| [REPORT.md](research/REPORT.md) | Original REA/static analysis of how Enhanced's minimap works, plus the first classic plan (§3 is partly superseded; see the notes inside) |
| [ENHANCED_NATIVE.md](research/ENHANCED_NATIVE.md) | Ghidra decomp of Enhanced and classic map natives: pipeline, side-by-side map, Step B matrix, radar-sourced threats, objective icon types |
| [PERF_REPORT_V1.md](research/PERF_REPORT_V1.md) | Frozen performance report schema v1 (the report contract with `steam-deck-scripts`); fixtures in `tools/fixtures/perf_reports/` |
| [PRIOR_RESEARCH.md](research/PRIOR_RESEARCH.md) | How the `steam-deck-scripts` research (decrypted-exe Ghidra analysis, Canvas POC) maps onto this |
| [evidence/](research/evidence/) | Script/Flash disassembly and native exec tables cited by REPORT |
| **plans/** | |
| [CI.md](CI.md) / [PLAN_CI.md](plans/PLAN_CI.md) | CI gates, scope, local commands and source-only fixture research |
| [TOOLS.md](TOOLS.md) / [PLAN_RELEASE_TOOLS.md](plans/PLAN_RELEASE_TOOLS.md) | Release/install, version synchronization and log diagnostics commands and design |
| [PLAN_DIRECT.md](plans/PLAN_DIRECT.md) | Step A (transient helper; v0.4.0–0.5.1) and Step B (transform in Python; implemented in v0.6.0, PHASE3 §3k) |
| [PLAN_V07.md](plans/PLAN_V07.md) | Run 9 findings → v0.7: source-clip corner markers, no-flicker rebuild, Enhanced dock with skew, ECHO/quest shift |
| [PLAN_V08.md](plans/PLAN_V08.md) | v0.8: Enhanced zoom (108% relative to the window), edge indicators, mission givers via classic's IMissionDirector script |
| [PLAN_V09.md](plans/PLAN_V09.md) | v0.9: Enhanced's box and clip-layer window; its fixed-zoom conclusion is superseded by PLAN_V10 |
| [PLAN_V10.md](plans/PLAN_V10.md) | v0.10: native `QuickAccessInit` objective-fit zoom (108% without objectives), full-icon edge handoff; N overlap matches Enhanced |
| [PLAN_V12.md](plans/PLAN_V12.md) | Coexisting with other HUD mods (Extended UI): research and a runtime merge of our minimap block into whichever HUD movie is installed |
| [PLAN_V13.md](plans/PLAN_V13.md) | One-file install: the mod builds the HUD movie from the player's own files (movie cache, Enhanced discovery, original art when Enhanced is missing); the path to the 1.0.0 public release |
| [PLAN_V11_MCP_HANDOFF.md](plans/PLAN_V11_MCP_HANDOFF.md) | Contract and task list for `steam-deck-scripts` to build the MCP performance adapter (PLAN_V11 decision 15): report schema v1, file layout, gates H0–H2, acceptance tests |
| [PLAN_V11.md](plans/PLAN_V11.md) | External profiler first: artifact separation, reversible wrappers, prior MCP report-format research, bounded reports/tests and overhead validation; instrumented build only as fallback |
| **log/** | |
| [PHASE0.md](log/PHASE0.md) | SDK on classic, probe runs: world→map formula, centring formula, `Angle` = yaw°, tick hook |
| [PHASE1.md](log/PHASE1.md) | `upkpatch.py` (movie swap, export and bulk-offset relocation). **§3's in-game "pass" was invalid** (see below) |
| [PHASE2.md](log/PHASE2.md) | `swfbuild.py`: the minimap movie (status-menu map tree copied in, root AS functions) |
| [PHASE3.md](log/PHASE3.md) | SDK mod, in-game runs, CI/release setup, v0.10 offline implementation, PLAN_V11 and the profiler add-on (§3b–3z) |
| [FRICTION.md](log/FRICTION.md) | What slowed work down (wrong assumptions, environment, agent shell/tool quirks, process) and ranked improvement suggestions |

## Installed right now (classic game folder)

| File | Version / SHA-256 |
|---|---|
| `WillowGame\CookedPC\Packages\Interface\GfxHUD_Minimap.upk` | **No longer used since v0.13.0; removed from the game folder by 2026-10-25 23:56 UTC.** It was v0.12.0 `a858eed8…d0f4` (block manifest for the runtime merge, PHASE3 §3ai), played in runs 19–20. Previous package `5eb071eb…61f1` is in the main checkout's `dist\v0.10.2-20261025T193718.875658Z\` (the v0.12.0 release bundle is in `dist\releases\0.12.0\`). Older: **v0.10 + run-14/16 fixes** `5eb071eb…61f1` (handoff sized from the icon's scale, §3aa; classic's gradient textures kept, §3ab; Enhanced threat diamonds, §3ad; multiplying tint, §3af). Backups in the worktree: diamond package `4a840f56…cabc` in `dist\v0101-run16\`, gradient-fix package `e2b687c1…ab51` in `dist\v0100-run15\`, wobble-fix package `5eefdf81…6d03` in `dist\v0100-wobblefix\`, first v0.10 package `5bae8e3f…bc29` in `dist\v0100\`; v0.9 package `dc1292c5…ab9d` in `dist\v090\` |
| `sdk_mods\classic_minimap.sdkmod` | **v0.14.7** `cca615b0…6664`, installed 2026-10-26 23:46 UTC, played in run 31 (PHASE3 §3au, §3av); v0.14.6 `e4fbda70…0ee1` (played in run 30) is in the main checkout's `dist\v0.14.6-20261026T234610.240604Z\`; v0.14.5 `45828006…1191` (played in run 29) is in the main checkout's `dist\v0.14.5-20261026T230836.401181Z\`; v0.14.4 `4a6d7886…a9ed` (played in run 28) is in the main checkout's `dist\v0.14.4-20261026T225604.292541Z\`; v0.14.3 `48d426bb…d8fc` (played in run 27) is in the main checkout's `dist\v0.14.3-20261026T224549.606761Z\`; v0.14.2 `5d2380c3…0547` (played in run 26) is in the main checkout's `dist\v0.14.2-20261026T223549.859286Z\`; v0.14.1 `0f6ca48f…8d3c` (played in run 24) is in the main checkout's `dist\v0.14.1-20261026T112120.130786Z\`; v0.14.0 `a2ea341d…f327` (played in run 23) is in the main checkout's `dist\v0.14.0-20261026T025655.020528Z\`; v0.13.1 `e3669056…62b5` (played in run 22) is in the main checkout's `dist\v0.13.1-20261026T013034.736255Z\`, v0.13.0 `4181461e…c013` in `dist\v0.13.0-20261025T235646.137461Z\`. Since v0.13 the mod builds its HUD movie from the game's own files, so `GfxHUD_Minimap.upk` is no longer used (PHASE3 §3aj). v0.12.0 `cfa93923…0d45` (played in runs 19–20) is in the main checkout's `dist\v0.12.0-20261025T230643.790982Z\`; v0.10.2 `e7d6da71…d42a` is in the same backup folder as the v0.10.2 package. Older backups: v0.10.1 in the worktree's `dist\v0101-run16\`, v0.10.0 in `dist\v0100-run15\`, v0.9.0 in `dist\v090\`, v0.8.1 in `dist\v081\`; older ones in the main checkout's `dist\v080\`, `dist\v070\`, `dist\v060\`, `dist\v051\` |
| `sdk_mods\classic_minimap_profiler.sdkmod` | **profiler 0.1.13** `9a15ba1f…cda9` installed 2026-10-26 23:46 UTC (0.1.12 `3f748e50…e33f` in the v0.14.6 backup folder; 0.1.11 `c4b1d19f…f7d5` in the v0.14.5 backup folder; 0.1.10 `84ab5543…c2de` in the v0.14.4 backup folder; 0.1.9 `2c63f50f…b60f` in the v0.14.3 backup folder; 0.1.8 `23018d24…1139` in the v0.14.2 backup folder; 0.1.7 `f4c7d39e…0147` in the v0.14.1 backup folder; 0.1.6 `fb723b37…1467` in the v0.14.0 backup folder; 0.1.5 `adb5d942…4287` in the v0.13.1 backup folder; 0.1.4 `370e2658…a0bd` in the v0.13.0 backup folder; 0.1.3 `988511a9…6376` in the v0.12.0 backup folder; 0.1.2 `497fe5c5…174e` in the same backup folder), optional (0.1.0 loaded and captured in run 14; backups in `dist\v0101-run16\`, `dist\v0100-run15\`). Delete it to remove |
| `sdk_mods\minimap_probe.sdkmod` | probe v0.2. Leave it disabled; it's not needed any more |
| `WillowGame\CookedPC\Packages\Interface\GfxHUD.upk` | **stock** `5c515c3e…3ea88` (backup: `dist\phase1\GfxHUD.orig.upk`) |

Saved option gotcha: your `sdk_mods\settings\classic_minimap.json` has **Top margin = 90** from older versions. The new default of 20 only applies to fresh settings, so set it to about 20 in MODS to clear the mission text.

**Uninstall:** delete `sdk_mods\classic_minimap.sdkmod` and `GfxHUD_Minimap.upk`.

The automatic-worker and maintenance tooling changes are source-only; installed versions and hashes above are unchanged.

## Build and test

For automated release builds, version bumps, installation and saved-log summaries, see [TOOLS.md](TOOLS.md).

```bash
# script disassembly: uedis.py reads decompressed packages from tools/pk/ (C_ = classic, E_ = Enhanced;
# it needs Core, Engine, GameFramework, GearboxFramework, GFxUI and WillowGame for the native-name table)
python -I tools/upkdecomp.py "<Borderlands>/WillowGame/CookedPC/WillowGame.u" tools/pk/C_WillowGame.u
python -I tools/uedis.py C '^WillowGFxHelperMap\.'
# movie
python -I tools/upkpatch.py extract "<Borderlands>/WillowGame/CookedPC/Packages/Interface/GfxHUD.upk" FlashMovie.HUD dist/phase2/HUD_classic.gfx
python -I tools/upkpatch.py extract "<Borderlands>/WillowGame/CookedPC/Packages/Interface/menus_ingame_redux.upk" FlashMovies.status_menu dist/phase2/status_menu.gfx
python -I tools/upkpatch.py extract "<BorderlandsGOTYEnhanced>/WillowGame/CookedPC/Packages/Interface/GfxHUD.upk" FlashMovie.HUD dist/phase2/HUD_enhanced.gfx
# both art variants (PLAN_V13): with Enhanced's movie, and without it (original art)
python -I tools/swfbuild.py dist/phase2/HUD_classic.gfx dist/phase2/status_menu.gfx dist/phase2/HUD_minimap.gfx dist/phase2/HUD_enhanced.gfx
python -I tools/swfbuild.py dist/phase2/HUD_classic.gfx dist/phase2/status_menu.gfx dist/phase2/HUD_minimap_original.gfx
python -I tools/test_minimap_as.py dist/phase2/HUD_minimap.gfx
python -I tools/test_minimap_as.py dist/phase2/HUD_minimap_original.gfx
# mod
python -I tools/test_minimap_mod.py dist/phase2/HUD_minimap.gfx
python -I tools/test_minimap_mod.py dist/phase2/HUD_minimap_original.gfx
python -I tools/build_sdkmod.py sdk_mods/classic_minimap dist
```

The test suites are an AS2 interpreter running the built movie's bytecode, and the real mod against stub `unrealsdk`/`mods_base`, with the native helper emulated from measured behaviour. Both must pass on both variants before installing; `tools/release.py` runs all of this, and with `--game`/`--enhanced` checks the mod's in-game build against the installed packages. Close the game before copying files. Bump versions with `tools/bump_version.py`.

Since v0.13 nothing but the `.sdkmod` is installed: the mod builds the movie in game from the player's own files (PLAN_V13). `upkpatch.py replace` is no longer part of a release.

## Hard-won facts (each one cost a debugging round)

1. **Classic `WillowGame.u` contains its own cooked copy of `GfxHUD.FlashMovie.HUD`** (plus its textures, `HUDDefinition` and the `hud_instance` template). It loads at startup, so **`GfxHUD.upk` on disk is never read**. The fix: ship `GfxHUD_Minimap.upk` (fresh GUID) and on enable set `hud_instance.MovieInfo` to its movie. That only affects HUDs spawned *after* the redirect (PHASE3 §3d).
2. **Never call `GFxMovie.Invoke` from Python.** Classic doesn't fill its `ASValue` return (seen as `Type=96`, garbage). Use `WillowGFxMovie.SingleArgInvokeS("MinimapCmd", "op~arg~…")` and read results back with `GetVariable*` (§3c/3e).
3. **Objects created from Python get garbage-collected:** a GPF in `pyunrealsdk.dll+0x240964` on attribute reads. Construct with `flags=ObjectFlags.KEEP_ALIVE` (`0x4000`, from `mods_base`) and clear it when done. Hold engine objects across ticks only through `WeakPointer` (§3f).
4. **The `WillowHUD.PostRender` hook never fires** in classic (it's `native`). Use `WillowPlayerController:PlayerTick`.
5. **The helper initialises before the zone's `LevelLandmarkAnchor` streams in.** The frame stays `none`, and its blank `themap` still has a finite width. So gate on `helper.Anchor` and require `map.maps._currentframe > 1` (§3h).
6. **Classic pawns have no `Health` property.** Use `Pawn.IsAliveAndWell()`. The visibility gates must fail independently (§3j).
7. **Objective markers go stale:** classic `FindObjects` only appends, and `UpdateObjects` rereads eight slots by ordinal. Rebuild with a fresh helper when the key changes. The key is the mission + target/turn-in definitions + `GRI.ActiveWaypointData[i].WaypointLocation` (100 UU grid) + live levels, baselined at capture (§3g/3j).
8. **Visibility** (Enhanced gets it free because its map is `p1.map`): hide while `IsLoadingMoviePlaying()` (the blue tunnel), `!myHUD.bShowHUD`, `bCinematicMode`, `bStatusMenuOpen`, `!IsAliveAndWell()`, `!p1._visible`, or within 3 s of a live-level set change (§3i).
9. **The executables are SteamStub-encrypted.** Classic uses **SteamStub 2.1 x86**: the AES key sits in an XOR'd payload, and an XTEA'd SteamDRMP.dll gives the field offsets. Enhanced uses **SteamStub 3.1 x64** (inline AES key in a 0xF0 header). `tools/steamstub.py` (needs pefile and pycryptodome) handles both and writes same-length analysis copies that change only the code section. It takes about 3 s. Classic's SHA-256 is `d3e941db…b5da` and Enhanced's is `92b53f7f…b5a2`, both matching the earlier research's copies. So the steam-deck-scripts research addresses (e.g. ApplyFlash `0x142a420`) apply directly. The desktop research zips (`Desktop\Borderlands-Research\…`) hold only stock game files, with the exe still encrypted.
10. **Classic native helper paths** are absolute `map.mask.*` / `map.maps.*` plus root `AddLandmark` / `UpdateLandmark` / `SetMapScale` / `InitDLC`. The movie provides them at `_root.map`.
11. **pyunrealsdk requires out parameters as positional arguments.** Call `io.GetEligibleMissions(pc, [])`, not `(pc)`; the result is `(ReturnValue, out…)`. Without it the call raises `TypeError: … missing 1 required positional argument` (run 12, §3n). Fakes for script functions with out parameters must use the same signature.

## Step B formula (from `sdk_mods\settings\classic_minimap_anchors.jsonl`, Fyrestone/Arid)

The anchor fields are `MapFrame` (zone frame label, e.g. `Arid`; Flash labels are lower-case and case-insensitive), `DLCMap`, `TextureSizeX/Y`, `DrawScale3D`, `Rotation.Yaw` and `Location`. They give the helper's `Transform` exactly:

```
θ = Yaw·2π/65536, c = cos θ, s = sin θ, dx = x − ax, dy = y − ay
qX = ( c·dx + s·dy) / (TextureSizeX · DrawScale3D.X)      # 1024·58.2003 = 59597.1
qY = (−s·dx + c·dy) / (TextureSizeY · DrawScale3D.Y)      # 512·233.131 = 119363.1
tr.x = (qY + 0.5)·CoordScale.X,  tr.y = (0.5 − qX)·CoordScale.Y
CoordScale.X = 1, CoordScale.Y = (ClipW/ClipH)/(TextureSizeX/TextureSizeY)   # ClipW/H = themap size at 100%
```

That's one zone so far. **The decomp (ENHANCED_NATIVE.md §3) shows that the true matrix also multiplies both extents by `DrawScale` and includes pitch/roll.** v0.6.0 builds that full matrix (`anchor_transform`) and reproduces the logged Arid helper Transform within 6.5e-8 relative error.

## Open items

- **Maintenance tooling:** a real installation through `install.py` remains unverified; install only when requested. Optional Deck deployment over SSH is deferred. Runtime foreign-HUD console feedback remains separate from `diag.py`'s saved-log detection.

- Hosted CI verification of automatic workers remains pending; local validation is recorded in PHASE3 §3s.
- **Player-built movie in game (PLAN_V13 step 6; the 1.0.0 gate's first part, decision 21):**
  - **PC done** (runs 21–23): both arts, Extended UI, the cache, the glyphs, and the old-package note.
  - **Deck (run 25, v0.14.1, §3ap):** Proton paths, original art, Extended UI merge (3.31 s) and the build (2.03 s) work. The game reset the ECHO panel behind the map; v0.14.2 re-applies the shift.
  - **Deck (run 32, v0.14.7, §3aw):** successful. Original art (built in 2.20 s), Extended UI merge 3.74 s, Angel centred at FOV 100 (FOV mod), ECHO panel shifted. Still to run on the Deck: Enhanced through `libraryfolders.vdf`, if installed.
- **v0.14.1 checks:** upright icons with "Rotate with player". The first Angel call's log answers the open questions: classic's mesh placement, whether `SetTranslation` works, and whether the native moves the mesh back. Compare "Angel position (experiment)" Classic with Enhanced.
- **Angel's video (PLAN_V14):** not the screen mesh (run 24) and not the root `vog` clip (run 26: empty during her call). It is a screen particle (`fx_PostProcess.VoG.part_VoG_Pulse`) drawn under the whole HUD, a 16:9 overlay kept on the camera's view axis at a fixed angle. Angel is centred in all 14 videos, so the top-right offset is the overlay's (§3aq–§3au). Shifting the overlay left worked in run 30. v0.14.7 makes it the default "Angel position" = Centered (0.28 of the width). Confirmed centred and stable in iron sights (run 31, §3av) and on the Steam Deck at FOV 100 (run 32, §3aw). Still to see: 4:3, and later missions (maybe `part_VoG_SimpleFade`).
- **Autosave icon (open by user decision, 2026-10-26):** `WillowHUD` draws `SavingIndicator_INST` natively above the minimap. No change for now.
- **Path to 1.0.0 (PLAN_V13 decisions 20–23):** PLAN_V14 for tuning (grilled after v0.13 is played); v0.14.x private builds; one pre-release through the release workflow's new `prerelease` input; then 1.0.0, the first public release.
- **Mutation floors for the moved builder files** (`hudmovie`, `swfbuild`, `as2asm`, `swfdeps`, `upk`) are configured at 70 but not measured; add them to `cosmic-ray.toml` and measure on demand.
- **Tuning pass (later, not game-breaking):**
  - **Runtime merge cost and level-change delay (run 19, PHASE3 §3ai):** the first merge took 3.4 s on the PC and 4.4 s on the Deck (2 x 0.7 s `RawData` reads, about 1.6 s of Python, 0.2 s write). v0.13 removes the read of our own movie (the merge uses the cached bytes); remaining ideas: speed up the bit reader in `swfmerge.walk_shape`, cache the merged bytes on disk keyed by the foreign movie's hash. Separately, after a level change the minimap came up about 10 s after the HUD (anchor wait 7.6 s plus the 3 s settle); compare with and without Extended UI before changing the settle rule.
  - **Zoom without a nearby objective (2026-10-25 screenshots):** in Skag Gully with "Roadkill" tracked, the map sat at the 108% floor, which doesn't match what Enhanced shows there. The zoom changing after a mission switch or turn-in is explained: the status-menu refit, fixed in v0.14.0 (PHASE3 §3al/§3am). What an off-map waypoint slot holds is still to check with F7's `zoom_fit.points` in such a zone (PLAN_V10, PLAN_V14).
- **Threat markers:** Enhanced's diamond (E shape 127, copied as 1310) replaces the drawn square, and it stays upright while rotating (seen in run 23, PHASE3 §3ad/§3an). Its size against Enhanced is still to check (PLAN_V14).
- **Profiler 0.1.0 (v0.11):**
  - Decide how decision 8's p95 requirement is accepted: the stub harness's noise (±0.7 ms paired) cannot resolve 0.05 ms.
  - In game, check that the SDK loads the add-on (relative imports inside the `.sdkmod`), the buttons and console lines work, and a 60 s capture saves.
  - Then run the PresentMon/MangoHud comparison runs (PLAN_V11 in-game validation).
  - H1 (adapter in `steam-deck-scripts`) and H2 (joint check) are pending.

- **v0.10.0:** install only when requested, with the game closed; compare fitted zoom with Enhanced, verify F8 refits and objective refreshes preserve zoom, check full-icon handoff at normal/enlarged icon sizes and while rotating, and verify F7's confirmation appears in the in-game console. North/objective overlap intentionally remains. No v0.10 in-game verification yet.
- **v0.9.0 in-game check** (PLAN_V09):
  - The minimap shows Enhanced's framed box (dark background, border) and a taller view.
  - North and objective edge markers sit on the box border.
  - Zoom and icon size still look right at 100%.
  - Custom position still works.
- **v0.8.1 in-game check** (carried into v0.9.0):
  - "!" at givers with an available mission and the turn-in icon at finished-mission givers (F7 `giver_icons` should be non-empty near Zed or a bounty board).
  - An objective reaching the window border becomes a single edge diamond, not a clipped icon plus a diamond.
- **v0.8.0 in-game check** (PLAN_V08; zoom, icons, tilt and north confirmed in run 12):
  - The zoom and icon size look like Enhanced (options: Zoom (vs Enhanced), Icon size).
  - "N" on the edge, rotating when "Rotate with player" is on.
  - A diamond on the edge pointing to off-window objectives.
  - "!" at mission givers with an available mission, and the turn-in icon at finished-mission givers; F7 shows `givers`/`giver_icons`.
- v0.7.0 confirmed in run 10: dock, ECHO shift, hidden templates, T-Bone.
- **v0.7.0 in-game check** (PLAN_V07 §6):
  - No stray diamond or arrow in Skag Gully or T-Bone.
  - Docked and tilted like the HUD (F7 `dock_mode: matrix`; `plain` means the runtime ignored the shear).
  - ECHO, Angel, quest title and checklist left of and below the map.
  - No blink in TK's Food.
  - Check the size; there's a Docked size option.
- v0.6.0 confirmed in run 9: radar dots, turn-in tint, DLC3 frame.
- Not yet exercised in game: rotate mode (`Rotation offset` is hidden, defaulting to 0), DLC zones (`InitDLC` loader), co-op/split-screen (v1 is player 1 only), the edge clamp near the art borders.
- **Step B remainder:**
  - v0.6.0 still constructs a helper for one call, for classic's exact list builders (`Init`) and DLC frame selection (`InitMapFrame`).
  - Dropping it entirely would mean re-implementing FindObjects' gates in Python: `CompassIconFrames[CompassIcon]`, `AssociatedOutpostName` vs `ActivatedTeleportersList`, and the fast-travel station list (`rstation`/`questionmark`), whose source wasn't pinned down.
- **Not done:** co-op buddy markers (WPRI records are skipped; they were stale statics before), and Enhanced's turnin/newmission artwork (v0.6.0 tints the diamond instead).
- **Ghidra for REA (installed 2026-10-24):**
  - Ghidra 12.1.4 is at `C:\Users\Charles\Tools\ghidra_12.1.4_PUBLIC` and Temurin JDK 21.0.12.1 at `C:\Users\Charles\Tools\jdk-21.0.12.1+1`; both SHA-256s matched their published values. REA requires 12.1.x, not 12.2.
  - `~/.claude.json` → `mcpServers.rea.env` sets `GHIDRA_INSTALL_DIR` and `JAVA_HOME` (backup: `~/.claude.json.bak-20261024-rea`). `rea doctor` reports Ghidra available.
  - The entry also sets `REA_GHIDRA_STARTUP_TIMEOUT_MS=2700000` and `REA_GHIDRA_DISABLED_ANALYZERS=Decompiler Switch Analysis,Function ID,Call Convention ID,Embedded Media,Non-Returning Functions - Discovered`. With REA's default 330 s deadline the import timed out.
  - **Each new REA session re-imports and re-analyses the exe in about 14 minutes** (862 s measured), because the Ghidra project is temporary. Open it once per session and keep it open.
  - Smoke test passed: `rea decompile … 0x142a420` (ApplyFlash) gave full pseudocode. The output is at `dist\decoded\rea\smoke_applyflash.json`.
  - A REA server started before that edit needs a session restart.
  - Decoded classic exe: `dist\decoded\Borderlands.decoded.exe`.
  - Decoded Enhanced exe: `dist\decoded\BorderlandsGOTY.decoded.exe`.
  - `tools/rea_client.py serve <spool>` / `call <spool> <tool> '<json>' [out]` keeps one REA MCP server per binary alive (imports take 15–18 min each). From Git Bash, use forward slashes in JSON paths. The pseudocode is in `dist\rea\{cls,enh}\fn\`; the findings are in ENHANCED_NATIVE.md.
- **Git is initialized.** Keep build outputs and game packages out of commits; commit and push only when requested. See AGENTS for commit conventions.
- The scratchpad `pk/` (decompressed packages) and `swf/` are temporary; regenerate them with the commands above.
