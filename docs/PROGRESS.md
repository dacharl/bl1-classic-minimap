# Classic Minimap: progress (updated 2026-10-24)

An Enhanced-style minimap for **Borderlands GOTY classic** (Steam app 8980, x86, v1.5.0.0), using the willow1 PythonSDK plus a separately shipped HUD movie package.

This page tracks where the project stands: what works, what's installed, how to build and test, and what's left. Agents start at [AGENTS.md](../AGENTS.md) and players read the [README](../README.md). Keep this page current: update the milestones, "Installed right now" and "Open items" with every release and in-game run. The details of each run go in [PHASE3](log/PHASE3.md).

## Where it stands

- **Automatic test workers (2026-10-24):** task branch `test/auto-parallel-workers` adds CPU-based defaults for unit and mutation tests, independent unit processes with merged coverage, and clean mutation-worker shutdown on Python 3.13. CI and local commands use the same defaults; see CI.md and PHASE3 §3s. No runtime or installed files change.
- **Feature worktree rebase:** v0.10/F7 work is rebased onto main `6f840a6`; both real-movie suites, all 11 automatic unit cases, coverage/mutation gates and lint pass. All 2,898 mutations complete without errors, timeouts or cleanup warnings (PHASE3 §3x).

- **Works in game (confirmed through run 12):** zone art, landmarks, player centring, radar enemy dots, the objective turn-in tint, the Enhanced-style dock with the HUD tilt, ECHO/mission text moved aside, no-flicker rebuilds, DLC3 maps, Enhanced zoom and icon size, the north marker, and hiding during the tunnel, menus and death.
- **Run 13 (v0.9.0):** box size matches the footage, but the map is ~2.5–3× less zoomed and objectives near the top edge are clipped (PHASE3 §3u).
- **Built, not installed:** v0.10.0 implements PLAN_V10's objective-fit zoom and switches to the edge diamond before an icon clips. Objective refreshes retain the fit; new anchors and explicit rebuilds refit. F7 reports the inputs and fitted/final zoom, and confirms the log write in the in-game console. Offline validation is recorded in PHASE3 §3v/3w; in-game checks remain pending.
- **Installed:** v0.9.0 (branch `worktree-enhanced-minimap-box`).
  - The map clip is now laid out like Enhanced's: its box art, and its 207.95 × 173.65 window instead of v0.8's squeezed 220 × 141.
  - Docking and icon size use Enhanced's own values; its fixed 108% zoom is corrected in v0.10 (PHASE3 §3t).
  - It includes v0.8.1's fixes: the edge diamond handoff, and the mission-giver calls ("!" and turn-in icons, still unplayed).
- **Earlier event:** run 11 crashed at startup because drive C: was full, not because of the mod (PHASE3 §3m).
- **Repository setup (2026-10-24):** Git initialized for a source-only initial commit; AGENTS now requires test-first behavior changes, Conventional Commits and no agent attribution. Build outputs and extracted game packages are ignored (PHASE3 §3o).
- **Release workflow (2026-10-24):** local branch renamed to `main`; manual GitHub Actions workflow packages the Python source as `.sdkmod` and publishes a version-tagged release. Hosted execution is pending; see README and PHASE3 §3p.
- **Source-only CI (2026-10-24):** lint, per-file line/branch coverage, all mod/packager mutants, workflow lint and repository/archive checks. Both existing suites pass against an asset-free fixture; hosted runs remain pending. See [CI.md](CI.md), PLAN_CI and PHASE3 §3q.
- **Worktree workflow (2026-10-24):** AGENTS requires a fresh worktree and a descriptive task branch for new coding tasks, with explicit user overrides for direct work on `main`. Branch names and worktree paths follow the no-attribution rule. CI/release setup was committed directly to `main` at the user's request (PHASE3 §3r).

## Milestones

| Version | What it delivered | In game |
|---|---|---|
| CI tooling | Automatic parallel unit/mutation workers with numeric overrides and combined unit coverage | Source-only; no installation |
| Phases 0–2 | SDK confirmed on classic (probe); `upkpatch.py` movie swap; `swfbuild.py` minimap movie | Probe runs 1–2 |
| v0.1–v0.2 | First mod; `SingleArgInvokeS` instead of `Invoke`; separate `GfxHUD_Minimap.upk` + template redirect | Runs 1–5: nothing shown, then GC crashes (§3b–3f) |
| v0.3–v0.4 | `KEEP_ALIVE` helper; objective refresh; transient helper gated on the zone anchor (Step A) | Run 6–7: working map (§3g–3h) |
| v0.5 | Visibility rules (tunnel, menus, HUD, death, 3 s settle); stale-objective key | Runs 7–8 (§3i–3j) |
| v0.6 | Transform computed in Python (Step B), radar enemy dots, objective status tint (from the Ghidra decomp) | Run 9: dots, tint and DLC3 confirmed (§3k) |
| v0.7 | Hidden icon templates, in-place rebuilds, Enhanced dock with the HUD tilt, ECHO/quest/check shift | Run 10: confirmed (§3l) |
| v0.8 | Enhanced zoom and icon size, north/objective edge indicators, "!"/turn-in mission givers | Run 11: disk-full crash (§3m). Run 12: zoom, icons, tilt and north confirmed; double marker and giver calls fixed in v0.8.1 (§3n) |
| v0.9 | Enhanced's box art and 207.95 × 173.65 window, dock/icon values, edge indicators on the box border | Run 13: box matches; fixed zoom and clipped icons need correction (§3u) |
| v0.10 | Native-style objective-fit zoom, full-icon edge handoff, F7 zoom diagnostics and console confirmation | Built; not installed or played (§3v/3w) |

## Doc map

Docs are cited across the code and docs by bare name (e.g. "PHASE3 §3l", "PLAN_V08 3"); every name below is unique.

| Doc | What's in it |
|---|---|
| **research/** | |
| [REPORT.md](research/REPORT.md) | Original REA/static analysis of how Enhanced's minimap works, plus the first classic plan (§3 is partly superseded; see the notes inside) |
| [ENHANCED_NATIVE.md](research/ENHANCED_NATIVE.md) | Ghidra decomp of Enhanced and classic map natives: pipeline, side-by-side map, Step B matrix, radar-sourced threats, objective icon types |
| [PRIOR_RESEARCH.md](research/PRIOR_RESEARCH.md) | How the `steam-deck-scripts` research (decrypted-exe Ghidra analysis, Canvas POC) maps onto this |
| [evidence/](research/evidence/) | Script/Flash disassembly and native exec tables cited by REPORT |
| **plans/** | |
| [CI.md](CI.md) / [PLAN_CI.md](plans/PLAN_CI.md) | CI gates, scope, local commands and source-only fixture research |
| [PLAN_DIRECT.md](plans/PLAN_DIRECT.md) | Step A (transient helper; v0.4.0–0.5.1) and Step B (transform in Python; implemented in v0.6.0, PHASE3 §3k) |
| [PLAN_V07.md](plans/PLAN_V07.md) | Run 9 findings → v0.7: source-clip corner markers, no-flicker rebuild, Enhanced dock with skew, ECHO/quest shift |
| [PLAN_V08.md](plans/PLAN_V08.md) | v0.8: Enhanced zoom (108% relative to the window), edge indicators, mission givers via classic's IMissionDirector script |
| [PLAN_V09.md](plans/PLAN_V09.md) | v0.9: Enhanced's box and clip-layer window; its fixed-zoom conclusion is superseded by PLAN_V10 |
| [PLAN_V10.md](plans/PLAN_V10.md) | v0.10: native `QuickAccessInit` objective-fit zoom (108% without objectives), full-icon edge handoff; N overlap matches Enhanced |
| **log/** | |
| [PHASE0.md](log/PHASE0.md) | SDK on classic, probe runs: world→map formula, centring formula, `Angle` = yaw°, tick hook |
| [PHASE1.md](log/PHASE1.md) | `upkpatch.py` (movie swap, export and bulk-offset relocation). **§3's in-game "pass" was invalid** (see below) |
| [PHASE2.md](log/PHASE2.md) | `swfbuild.py`: the minimap movie (status-menu map tree copied in, root AS functions) |
| [PHASE3.md](log/PHASE3.md) | SDK mod, in-game runs, CI/release setup and v0.10 offline implementation (§3b–3x) |
| [FRICTION.md](log/FRICTION.md) | What slowed work down (wrong assumptions, environment, agent shell/tool quirks, process) and ranked improvement suggestions |

## Installed right now (classic game folder)

| File | Version / SHA-256 |
|---|---|
| `WillowGame\CookedPC\Packages\Interface\GfxHUD_Minimap.upk` | `dc1292c5…ab9d` (built on the `worktree-enhanced-minimap-box` worktree; Enhanced box and window layout, turnin/newmission/north art, `MinimapEdges` on the box border) |
| `sdk_mods\classic_minimap.sdkmod` | **v0.9.0** `6df0c878…d7d7`, played in run 13 (PHASE3 §3u). v0.10.0 is built only. v0.8.1 backup is in the worktree's `dist\v081\`; older backups are in the main checkout's `dist\v080\`, `dist\v070\`, `dist\v060\`, `dist\v051\` |
| `sdk_mods\minimap_probe.sdkmod` | probe v0.2. Leave it disabled; it's not needed any more |
| `WillowGame\CookedPC\Packages\Interface\GfxHUD.upk` | **stock** `5c515c3e…3ea88` (backup: `dist\phase1\GfxHUD.orig.upk`) |

Saved option gotcha: your `sdk_mods\settings\classic_minimap.json` has **Top margin = 90** from older versions. The new default of 20 only applies to fresh settings, so set it to about 20 in MODS to clear the mission text.

**Uninstall:** delete `sdk_mods\classic_minimap.sdkmod` and `GfxHUD_Minimap.upk`.

The automatic-worker tooling changes are source-only; installed versions and hashes above are unchanged.

## Build and test

```bash
# script disassembly: uedis.py reads decompressed packages from tools/pk/ (C_ = classic, E_ = Enhanced;
# it needs Core, Engine, GameFramework, GearboxFramework, GFxUI and WillowGame for the native-name table)
python -I tools/upkdecomp.py "<Borderlands>/WillowGame/CookedPC/WillowGame.u" tools/pk/C_WillowGame.u
python -I tools/uedis.py C '^WillowGFxHelperMap\.'
# movie
python -I tools/upkpatch.py extract "<Borderlands>/WillowGame/CookedPC/Packages/Interface/GfxHUD.upk" FlashMovie.HUD dist/phase2/HUD_classic.gfx
python -I tools/upkpatch.py extract "<Borderlands>/WillowGame/CookedPC/Packages/Interface/menus_ingame_redux.upk" FlashMovies.status_menu dist/phase2/status_menu.gfx
python -I tools/upkpatch.py extract "<BorderlandsGOTYEnhanced>/WillowGame/CookedPC/Packages/Interface/GfxHUD.upk" FlashMovie.HUD dist/phase2/HUD_enhanced.gfx
python -I tools/swfbuild.py dist/phase2/HUD_classic.gfx dist/phase2/status_menu.gfx dist/phase2/HUD_minimap.gfx dist/phase2/HUD_enhanced.gfx
python -I tools/test_minimap_as.py dist/phase2/HUD_minimap.gfx
python -I tools/upkpatch.py replace dist/phase1/GfxHUD.orig.upk FlashMovie.HUD dist/phase2/HUD_minimap.gfx dist/phase2/GfxHUD_Minimap.upk --new-guid
# mod
python -I tools/test_minimap_mod.py dist/phase2/HUD_minimap.gfx
python -I tools/build_sdkmod.py sdk_mods/classic_minimap dist
```

The test suites are an AS2 interpreter running the built movie's bytecode, and the real mod against stub `unrealsdk`/`mods_base`, with the native helper emulated from measured behaviour. Both must pass before installing. Close the game before copying files. Bump `__version__` and `pyproject.toml` together.

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

- Hosted CI verification of automatic workers remains pending; local validation is recorded in PHASE3 §3s.

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
