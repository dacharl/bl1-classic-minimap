# Friction log

This log records what slowed work down, why, and how to avoid it next time. Add an entry whenever something costs an extra in-game round, a broken tool run, or rework. Keep each entry short:
- **what happened**;
- **cause**;
- **workaround** (what got past it this time);
- **fix** (what would prevent it).

The suggestions at the end are ranked by how much time they would have saved.

## Session of 2026-10-24 (v0.5.1 → v0.9.0, runs 9–12)

### Assumptions that cost an in-game round

| What happened | Cause | Workaround | Fix |
|---|---|---|---|
| Run 12: no mission-giver icons (`TypeError: … missing 1 required positional argument`) | Assumed pyunrealsdk lets out parameters be omitted; the test fake accepted that call | Pass `[]`; fake signatures now match | Fakes for script functions must copy the real parameter list (see suggestion 4); PROGRESS fact 11 |
| Run 12: "double" waypoint at the window border | The edge diamond and the clipped objective icon were both visible; the handoff wasn't designed | Hide the icon while the diamond shows | Design marker state changes explicitly and test the in-between state |
| v0.8 → v0.9: view shorter than Enhanced | The window was sized from Enhanced's edge thresholds (±110 → "220 wide") instead of its actual mask shape | Read E sprite 187 and copied the real box and window shapes | Take geometry from the source asset (shape bounds, placements), not from constants in code |
| Run 9: stuck diamond and arrow | Icon template clips placed on zone frames were never hidden; Enhanced hides them in `SetMapFrame` | Hide templates; show duplicates explicitly | Before driving a copied Flash clip, read how the original owner initialises it |

### Environment

| What happened | Cause | Workaround | Fix |
|---|---|---|---|
| Run 11: crash at startup, `unrealsdk.log`/`Launch.log` 0 bytes, no dump | Drive C: at 0 bytes free (Ghidra servers left running plus downloads added to it) | Freed space; shut down REA servers; deleted the download zips | If a crash comes with empty logs, check free space first; always `close_binary` and stop REA servers after decompiling |
| REA in this session had no Ghidra | The MCP server started before `GHIDRA_INSTALL_DIR`/`JAVA_HOME` were added to `~/.claude.json` | `tools/rea_client.py` keeps a private REA server per binary | Configure REA before the session starts; restart after config changes |
| Each Ghidra import took 15–18 min, per session and per binary | REA's Ghidra project is temporary; snapshots store Evidence, not the analysed program | Kept servers alive across many queries; batched `batch_decompile` calls | Plan all REA questions for a binary together; reuse saved pseudocode in `dist/rea/*/fn/` before re-importing |
| Newest Ghidra (12.2) rejected | REA 6.7.0 accepts only 12.1.x | Installed 12.1.4 | Run `rea doctor` before choosing versions |
| Steamless can't run here | It needs .NET Framework 4.5.2 | Re-implemented the decode (`tools/steamstub.py`) and checked hashes against the earlier research | None needed; the tool now exists |

### Shell and tool quirks (agent tooling)

| What happened | Cause | Workaround |
|---|---|---|
| A literal NUL byte written into `tools/swfbuild.py` | The Bash wrapper collapses `\\` inside heredocs, so `b'\\0'` became `b'\0'` → NUL | Write scripts with the Write tool, never through heredocs; fixed with a byte-level script |
| A `cat >> doc <<'EOF'` heredoc with markdown backticks (PLAN_V12 session) executed `swfmerge.py`, `bump_version.py` etc. as shell scripts and wrote nothing; heredoc `\x00` escapes in a Python patch script also wrote NUL bytes into a test file | The wrapper `eval`s the command, so backticks in a quoted heredoc still run, and backslashes collapse | Nothing was changed (checked with `git status`); redo with Write/Edit | Use the Write or Edit tool for any text containing backticks or backslashes (already the rule above) |
| `sed` patterns with backticks ran as commands; `$VAR` expanded to empty (a write was aimed at `/MEMORY.md`) | The wrapper re-quotes commands through `eval` | Use the Edit tool for text changes; spell out paths instead of using shell variables |
| Worktree session refused `python -c …` and commands that use variables | The isolation guard can't prove such commands aren't git | Put analysis code in scratchpad `.py` files; use literal paths |
| Bash failed with exit 127 on every command for a while | The wrapper couldn't write its cwd file in `%TEMP%` (disk was fine) | Fell back to PowerShell |
| Python output crashed in PowerShell after the work was done | The cp1252 console can't encode `→` etc. | Set `PYTHONIOENCODING=utf-8`, or avoid printing non-ASCII |
| Wrong character types in `swftimeline`/bounds (e.g. `81`, `83`, `87` shown as `GFxGradientImage` or "not a sprite") | `swfdeps.Movie.defs` keys GFx extension tags (1001–1009) by the same u16 as characters | Scanned tags directly | Suggestion 3 |
| `native.py natives` found no thunk for `SetMissionBitfields` | Resolver pattern gap | Used the script API (`GetEligibleMissions`) instead | None needed |

### Process

| What happened | Cause | Fix |
|---|---|---|
| PHASE3 got two §3o entries | Two writers (the repository setup and this session) picked the next letter without checking | Check the last heading right before adding; renumber the later one (done: §3p) |
| Worktree had no build inputs | `dist/` and `tools/pk/` are ignored, so a new worktree starts without them; inputs had to be copied from the main checkout, and backups are now split between two `dist/` folders | Suggestion 2 |
| Each release repeated the same manual steps: version bump in 2 files, build, game-closed check, backup, copy, hash check, bulk-data check | No release tooling | Suggestion 1 |
| Renaming and moving docs touched many references | Bare-name citations across code and docs | Scripted the change; the link checker caught nothing broken (keep running it) |
| One very long session reached compaction more than once | Many versions and in-game rounds in one conversation | Commit per version on a branch, and start a fresh session per feature (PROGRESS and AGENTS make that cheap) |

## Rebase follow-up (2026-10-24, v0.10)

Rebase follow-up (2026-10-24, v0.10): main removed an unused `struct` import that the box branch's new AS assertions need, and the CI fixture lacked box/window shapes 81/82. The rebase merged cleanly but the real AS suite and asset-free CI suite exposed both issues; restore the import and fixture shapes. Main and the branch also reused PHASE3 §3p/3q, so the branch entries were renumbered §3t/3u. Run both real-movie and source-only suites after rebases, and check log headings for semantic collisions even when Git reports no conflicts.

F7 follow-up mutation run: all 2,898 cases completed and gates passed, but eight workers emitted Windows `WinError 32` when removing temporary workspace directories during shutdown. The runner still wrote complete reports and exited 0. Keep test outcomes separate from cleanup warnings; investigate worker shutdown/temporary-directory ownership before changing the mutation runner. No source behavior was affected.

Second rebase onto automatic workers: PROGRESS had an open-items conflict during both replay and stash restoration. Kept both sides' entries; main's new §3s required shifting branch sections to §3t–3w. This host's Git predates `git restore`; used `git reset HEAD -- .` to unstage restored changes without touching file contents. Automatic-worker shutdown now includes main's Python 3.13 cleanup fix; the full 2,898-case rerun passed without cleanup tracebacks.

## Profiler add-on (2026-10-24, PLAN_V11)

| What happened | Cause | Workaround | Fix |
|---|---|---|---|
| The first benchmark showed attached p50 15 ms vs 1.7 ms detached | `tracemalloc` was running during the attached timing runs and slows every allocation | Memory measured in separate runs; timing runs untraced | Never trace or profile inside a timing measurement |
| Two p95 comparisons (unpaired, then paired) could not resolve a 0.05 ms limit | The stub harness's per-tick noise (±0.7 ms, Python AS interpreter) dwarfs the effect | The benchmark reports `unresolved` instead of pass/fail; a wrapper-cost estimate is shown alongside | State a measurement's noise floor before choosing a pass threshold; decide acceptance in game or with a lower-noise harness |
| One coverage combine reported "Combined 5 files, skipped 1" and far lower profiler coverage | Stale `.coverage.*` files from an earlier interrupted run were combined | Deleted `dist/ci/.coverage*` and reran | Clear `dist/ci/.coverage*` before a local coverage run if a previous one was interrupted |
| Quality tools missing (`No module named coverage`) | The pinned CI tools live in the main checkout's `.venv`, not the system Python | Used `C:\Users\Charles\Dev\bl1-classic-minimap\.venv\Scripts\python.exe` | Worktrees share the main checkout's `.venv` (CI.md local commands) |
| A profiler-only mutation run was stopped halfway to edit `profiler.py` | Workers mutate copies taken at start; editing the source mid-run risks mismatched mutants | Stopped, edited, reran once | Finish source edits before starting mutation runs |
| A version bump added a UTF-8 BOM to `__init__.py` and `pyproject.toml` | PowerShell 5.1 `Set-Content -Encoding utf8` writes a BOM | Stripped with a script before testing | Edit files with the Edit tool; never `Set-Content` source files |
| Run 15: Tartarus showed T-Bone's map | The DLC loader is a frame action that runs only on frame entry; same-frame `gotoAndStop` is a no-op | Leave the frame (`none`) when the DLC package changes | The test fakes must model frame-entry actions for copied Flash frames |
| Bright damage indicator and a green/red/white minimap box, present since the box (and likely since the first package) | GFx keys external gradient images by file-order gradient index; inserting gradient shapes shifted classic's numbering | Shift classic's tag 1003 ids by the number of inserted gradient fills | When inserting definitions into a GFx movie, check position-keyed GFx tags (1003 gradients), not only character ids; compare the stock HUD's look after each new insertion |
| Run 14: objective marker flipped between edge diamond and icon while standing still | The handoff measured the icon's live `_width`, but classic's objective art animates (a ring scaling 1.0 → 2.2) | Size from the icon's scale and the art's static base shape (`OBJECTIVE_HALF`) | Before measuring a copied Flash clip, check its timeline for animation (`swftimeline.py`); the AS VM's clips are static, so model animation in tests |
| The full mutation run stalled for an hour at 1,200/3,866 with all 8 workers stuck | Profiler mutants created infinite loops; on Windows Cosmic Ray's timeout kills only the venv launcher (no `killpg`), the suite survives and holds the output pipe | Stopped the run; `tools/watchdog_run.py` makes each suite exit at a deadline and `test_mutants.py` kills process trees; verified end to end with Cosmic Ray's own `run_tests` | Check mutation-log progress timestamps during long runs; every test command must end itself, never rely on the caller's kill |
| The restarted full mutation run stalled again at 3,850/3,866 | Some mutants spin in one C call (holding the GIL), so the in-process watchdog never ran; Windows Cosmic Ray kills only its direct child | Suites in a kill-on-close job object (Windows) and in the caller's process group (POSIX); reproduced and verified with Cosmic Ray's own kill function | Process lifetime must be enforced by the OS, not by threads in the hung process; test hang handling against the real caller's kill path |
| `PYTHONIOENCODING` had no effect on a `python -I` script | Isolated mode ignores `PYTHON*` environment variables | `sys.stdout.reconfigure(encoding='utf-8')` in the script, or write to a file | Don't rely on `PYTHONIOENCODING` with `-I` |

## Session of 2026-10-24/25 (v0.10.0 → v0.10.2, runs 13–17, profiler 0.1.x)

Items already logged above as they happened: the profiler benchmark and coverage traps, both mutation stalls, the run 14–15 fixes (wobble, gradients, DLC frame), and the BOM. These are the rest.

### Process and workflow

| What happened | Cause | Workaround | Fix |
|---|---|---|---|
| Six installs in two days, each a hand-written PowerShell block (tasklist, back up to a new `dist\v…` folder, copy, hash each file, check the stock HUD, then edit PROGRESS and PHASE3) | No install tool; suggestion 1 from the previous session was never built | Careful copy-paste; every install was verified | Build `tools/install.py` (suggestion 1). The backup folders (`v0100`, `v0100-wobblefix`, `v0100-run15`, `v0101-run16`) became ad hoc names |
| One mod fix cascaded into seven files: mod version ×2, the profiler allowlist, profiler version ×2, all 21 fixtures, two contract docs | The profiler's exact core allowlist (decision 14) plus fixtures that embed the producer version | A guard test now catches a missing allowlist entry | A bump tool that updates every field and regenerates the fixtures (suggestion 3) |
| Full mutation runs took about 75 minutes, two stalled, and all results were lost each time (the log only had the last progress line) | `run_mutations.py` creates a fresh database per run, has no resume, and nothing notices a stall | Kept a copy of the log; read the counts from its last line | Resume from the existing database, plus a no-progress alarm (suggestion 4) |
| Commits had to be split by hand: PROGRESS, PHASE3, README and AGENTS each mixed several features | Records for parallel work go into shared files | A strip-and-restore script for one split; grouping shared files with their nearest commit for the rest | Commit per feature as soon as it's validated, not in batches |
| A multi-line `Edit` on the PROGRESS table failed | The old text cut table rows mid-line, so it wasn't contiguous | Redid it as three single-row edits | Edit whole lines; for tables, one row per edit |

### Diagnosis

| What happened | Cause | Workaround | Fix |
|---|---|---|---|
| Every in-game report needed a new throwaway parser (F7 fields, zoom inputs, anchors, profiler summary, screenshot crops) | F7 prints a Python dict into the log; nothing summarizes it | Scratch scripts `diaglast/diagall/diagzoom/anchors.py`, `crop_box.py` | `tools/diag.py` (suggestion 2) |
| On the Deck the mod looked dead: no minimap, no message | The only hint went to `unrealsdk.log`; nothing on screen. Another HUD mod (Extended UI) had replaced the movie, and the hint ("load a save") was wrong for that case | Read the uploaded Deck log; the user disabled Extended UI | In-game console messages for idle states, naming a foreign HUD movie (PLAN_V12 item 2) |
| Finding the Deck's log took a round trip; F7 needs a keyboard on the Deck | Paths and input differ under Proton | Explained in chat | A README section for Steam Deck testing (log path, settings path, F7 via Steam Input) |
| GFx questions (art size, gradients, animation, exports) each needed a new scratch script | Inspection tools cover timelines and dependencies but not shape geometry, colours or gradient mapping | `shapebounds/shapedump/shaperender/gradscan/gradmap/rawdef.py` in the scratchpad | Promote them into `tools/swfinspect.py` (suggestion 5) |
| Two assumptions about copied art broke in game: the icon's width pulses, and `setRGB` flattens every layer | The AS VM models clips as static boxes with no timeline or colour layers | Measured with `swftimeline.py`; regression tests added afterwards | Before measuring or colouring a copied clip, list its frames and layers; let the VM model frame-varying sizes where measurements depend on them |

### Environment and agent tooling

| What happened | Cause | Workaround |
|---|---|---|
| `start_session` refused `C:/Users/.../steam-deck-scripts`, then needed the user to trust the repository | The app wants the native Windows spelling and a trusted folder | Retried with backslashes; the user then declined the session |
| `Select-Object -First N` after a native command made PowerShell report exit 255 | The pipeline closes early; the command itself succeeded | Ignored after checking the output |
| Reading the Codex grilling session needed a JSONL parser | No tool for other agents' transcripts | Scratch `codextail.py` |
| Usage limits interrupted two long turns | Long test, mutation and benchmark runs inside a turn | Resumed from the summary; background runs survived |

## Suggested improvements (ranked)

**2026-10-25 status:** items 1–3 are implemented and validated offline (PHASE3 §3ah;
[usage](../TOOLS.md)). Real installation through the tool is unverified; optional Deck SSH deployment
is deferred. Item 4 is now the highest-ranked pending tool.

**2026-10-26 status (after v0.13–v0.14.1, five installs):**
- `install.py` has now done five real installs, each hash-verified (PHASE3 §3aj–§3an).
- Since v0.13 there's no package: `release.py` builds both art variants and checks the in-mod build against
  the game folders.
- Item 9's visible status is partly done: status lines in the log, the console and the MODS description
  since v0.12 and v0.13.
- Item 11 is done.

Pending tools, in priority order:
1. item 14 (`check_all.py`);
2. item 15 (a ship pipeline);
3. item 5 (`swfinspect.py`: a start exists, uncommitted);
4. item 16 (a `diag.py` timeline);
5. item 4 (resumable mutations);
6. item 17 (REA recipes);
7. item 18 (zone scales, post 1.0).

1. **Release and install tooling — implemented offline** (six manual installs motivated this).
   - `tools/release.py`: bump `__version__` and `pyproject.toml` together, run both suites, build the package (`--new-guid`) and `.sdkmod`.
   - `tools/install.py`: refuse while `Borderlands.exe` runs, back up the installed files to `dist/vNNN/`, copy, verify SHA-256, and run the package bulk-data check.
     - Back up to a dated folder named after the version being replaced.
     - Install the profiler only with `--profiler`.
     - Print the PROGRESS rows to paste.
     - Optionally target the Deck over SSH.
2. **`tools/diag.py`: read any `unrealsdk.log` — implemented** (local, or a copy from the Deck):
   - phase and template/HUD MovieInfo, flagging a foreign HUD movie;
   - the last N F7 snapshots, with `zoom_fit` decoded (points, raw, final);
   - warnings since startup, and map-ready and rebuild lines with timestamps;
   - a summary of `classic_minimap_anchors.jsonl` and the latest profiler summary.
3. **`tools/bump_version.py` — implemented:** bump the mod (both fields), add it to the profiler's `SUPPORTED_CORE_VERSIONS`, bump the profiler (both fields), regenerate `tools/fixtures/perf_reports/`, and update the version lines in PERF_REPORT_V1 and the handoff. Write bytes without a BOM.
4. **Resumable, watched mutation runs:**
   - `run_mutations.py --resume` keeps the Cosmic Ray database and runs only pending items.
   - It writes `dist/ci/mutations.json` after every progress line, not only at the end.
   - A no-progress timeout (e.g. 10 minutes) prints the stuck workers' processes and exits, instead of hanging.
5. **`tools/swfinspect.py`** from this session's scratch scripts:
   - `bounds` (shape/sprite bounds, including GFx id collisions);
   - `dump` (fills, line styles, vertices);
   - `render` (wireframe PNG);
   - `gradients` (per-shape gradient index → tag-1003 image, and stock-vs-built comparison);
   - `frames` (which frames change a sprite's size or colour).

   Also add the "classic shapes keep their gradient images" check to the real-movie AS suite when `HUD_classic.gfx` is present.

   **2026-10-26:** an uncommitted start exists in `.worktrees/mutation-swf-tools` (`tools/swfinspect.py`, its tests,
   `docs/plans/PLAN_MUTATION_SWF_TOOLS.md`); finish that rather than starting again. This session added scratch
   helpers to fold in:
   - fonts and glyphs (`fontscan`, `fontpos`);
   - named-clip placement matrices at the root and in sprites (`placements`, `spriteplacements`);
   - per-frame placements with children (`frames112`, `spritekids`);
   - shape fills and bounds that skip same-id GFx records (`shapeinfo`).

   Also: `upkprops` should decode common structs (`Vector`, `Vector4`, `Rotator`, `Color`), not show
   `<16 bytes>` (`vogpos.py` did it by hand).
6. **One shared input cache for every checkout and worktree.** `tools/inputs.py` would extract the classic HUD and status-menu movies and the Enhanced HUD from the game installs into a cache outside the repo (e.g. `%LOCALAPPDATA%\bl1-classic-minimap\inputs`, overridable). The build commands would read from there, and backups would go there too.
7. **Fix the GFx ID collision for inspection tools.** Make the `swfdeps.Movie` lookup prefer standard SWF definitions over GFx extension tags, behind a flag, and verify that `swfbuild`'s closure is unchanged byte for byte before switching it on.
8. **Check fake signatures against the packages.** Add a test helper that reads a script function's parameters (including `out`) with `uedis`/`upk`, and asserts each fake's Python signature matches. It would have caught run 12 offline.
9. **In-game self-test and visible status (F7 extension).** Exercise each risky SDK call once (giver calls, the `transform.matrix` read-back, radar read) and log pass/fail, so one key press validates new assumptions before a full play-through. Echo the phase and any idle reason (foreign HUD, missing package, no anchor) to the in-game console, not only the log.
10. **Promote the scratch helpers into `tools/`:**
   - `bulkcheck.py` → `tools/upkcheck.py` (package bulk-data validation);
   - `checklinks.py` → `tools/checklinks.py`;
   - `strrefs.py` (x64 string references) → `tools/strrefs.py`.
11. **Agent shell rules in AGENTS.md** (done in the previous session; this session added the `-I`/`PYTHONIOENCODING` note): use the Write tool for scripts (no heredocs with backslashes), the Edit tool for text, literal paths in worktrees, PowerShell when Bash's wrapper fails, and `PYTHONIOENCODING=utf-8`.
12. **Commit per version** on the feature branch once the user approves, so each in-game run maps to a commit and diffs stay reviewable. This session showed the cost of batching: one five-commit split of 33 changed files.
13. **A Steam Deck testing section in the README:** log and settings paths under Proton (including the SD card), F7 through Steam Input or the on-screen keyboard, and known HUD-mod conflicts.
14. **`tools/check_all.py`** (every change this session ran the scratch `checkall.ps1`):
   - build both art variants from `dist/phase2`, and run both real-movie suites on each;
   - run the unit tests with coverage, then `coverage json`, the coverage gate, Ruff and the repository gate;
   - print one pass/fail summary.

   Cross-platform Python avoids PowerShell's exit-code quirks (`Select-Object -First`, `NativeCommandError` on
   stderr).
15. **A ship pipeline** (`tools/ship.py`; the same sequence ran five times, v0.13.0 → v0.14.1):
   1. `bump_version.py`;
   2. `release.py` with `--game` both with and without `--enhanced`, so both in-mod builds are checked against
      the real files;
   3. the install dry run, then `install.py`, still refusing while the game runs;
   4. independent SHA-256 checks of the installed files and backups;
   5. print the PHASE3 install lines and PROGRESS rows.

   Commits stay manual and per version (item 12).
16. **A `diag.py` timeline** (the SDK log was grepped by hand repeatedly):
   - `--timeline`: HUD-movie build and cache lines with timings, merges and refusals, map shown and hidden with
     reasons, map ready and rebuilds, and Angel-call lines;
   - F7 fields beyond `zoom_fit`: `hud_movie`, `angel`, `echo_x` and `hud_shifted`.
17. **REA recipes in `rea_client.py`:**
   - read arguments from a JSON file, so PowerShell can't strip the quotes;
   - `native <name>`: string → table slot (`search_bytes`) → the startup `mov` that fills it → the function
     address;
   - close the target and stop the server automatically on exit or idle.
18. **Zone scale tool (post 1.0, for the fixed zoom mode):** promote the scratch `zonescale.py`. It reports metres
   across the window at 100% per recorded anchor, and the art size at 100% per zone frame from the movie rather
   than from `ClipSize`.

## Maintenance tooling implementation (2026-10-25)

| What happened | Cause | Workaround | Fix |
|---|---|---|---|
| Both real-movie suites failed on the primary checkout's existing output before any source changes | The ignored `HUD_minimap.gfx` was older than the current source (old threats/tint behavior) | Rebuilt in the task worktree from the explicitly selected local inputs; both suites passed | Build and test a fresh movie in `release.py`; never treat an existing ignored artifact as current |
| Baseline Git tests and the install test's process check failed inside the sandbox | Temporary Git repository creation and `tasklist` needed access beyond the initial tool sandbox | Reran those tests with the required access; they passed | Distinguish environment refusals from behavior failures; process-query errors must still refuse installation |
| An initial contract-version edit replaced a historical producer version in the allowlist | Broad replacement in the introduction changed both the current producer and history | A CLI scenario caught the missing old version before completion | Edit the current-version fields separately and extend, rather than replace, the documented producer list |

## Player-built movie implementation (2026-10-25, PLAN_V13)

| What happened | Cause | Workaround | Fix |
|---|---|---|---|
| Writing to a freshly created `.worktrees/<task>` worktree was refused | The session was isolated to its own `.claude/worktrees/...` worktree | Removed the empty worktree; branched the task from `main` inside the session's worktree | In an isolated session, create the task branch in the session's own worktree |
| The check script reported "FAILED: build" although the build succeeded | `Select-Object -First 1` after a native command makes PowerShell report exit 255 (a known quirk) | Captured output with `Out-String` and printed its first line | Never pipe a native command into `Select-Object -First` when its exit code matters |
| A mod-suite edit raised `UnboundLocalError` for `contextlib` | A later `import contextlib` inside `main()` made the name local to the whole function | Moved the imports to the module top | Import at module level in the long scenario functions |
| A workflow test pinned the current profiler version (`... and 0.1.3`) and failed after the bump | The bump scenario reused the live version numbers | Read the current version from the source and bump to versions above it | Version-independent bump scenarios |

## Runs 21–23 and PLAN_V14 (2026-10-25/26, v0.13.1 → v0.14.1)

| What happened | Cause | Workaround | Fix |
|---|---|---|---|
| The session's REA tools failed with `provider_unavailable` | That MCP server started without `GHIDRA_INSTALL_DIR`/`JAVA_HOME` | Used `tools/rea_client.py`, which sets them | AGENTS REA notes: prefer `rea_client.py` |
| `rea_client.py call` from PowerShell failed to parse its JSON | PowerShell 5.1 strips double quotes from arguments to native programs | Ran the calls from Git Bash | AGENTS REA notes |
| A REA decompile of a native failed ("no procedure starts at") | The exec thunk is reached only through a table slot filled at startup, so Ghidra created no function | Found the slot via `search_bytes` and the startup `mov`, then stopped: the fix didn't need the draw code | AGENTS REA notes |
| Angel's overlay was misread twice (map depth, then the HUD's `vog` clip) before the cause was found: a 3D screen mesh | It was assumed to be a HUD clip because it looked like one | Searched the script for the feature (`PlayVoGEchoCall`) | Before tuning a HUD element's depth or position, check that it is in the movie at all |
| A "match Enhanced" colour claim was wrong (gold turn-in) | The v0.6 tint was our own choice, later taken as Enhanced's | Read Enhanced's landmark frames and fills | Check Enhanced's movie art before calling a behaviour Enhanced's |
| Two similar button names ("Rebuild now", "Rebuild HUD movie") confused the user | Names written without comparing them side by side | Renamed both (PLAN_V14 decision 6) | Review option names together when adding one |
| A mod-suite scenario guessed a giver position and failed | The guess didn't match the live objective slot | Read the slot's location in the test | Derive fixture positions from the state under test |
| The v0.14.1 Angel spike hooked a path that never ran (run 24); the ECHO panel was reset behind the map on the Deck (run 25) | The run-23 overlap was diagnosed from static analysis, not a runtime read of the HUD; the HUD shift was applied once and assumed to stay | v0.14.2 re-applies the shift each tick and logs the `vog` clip | Before a spike, log the suspect clip's live placement (F7) at the moment the problem is on screen; re-assert any position we set on a clip the game owns |
| Angel's video was chased through three wrong elements (screen mesh, root `vog` clip, ECHO panel) before the screen particle (run 26) | Each guess came from one matching name (`PlayVoGEchoCall`, `texture1`) instead of every script path that touches the ECHO video | Listed every function that uses `CurrentEchoCall.Video` / `Video` (`uedis.py C '(?i)vog\|echocall\|screenparticle'`) | For a "where is X drawn" question, enumerate all script users of X's data first, then instrument all of them in one build |
| A PHASE3 append through a Bash heredoc ran its backticks as commands | Backticks in Markdown inside the Bash wrapper's `eval` | Re-did the append with the Edit tool | AGENTS already says: Edit tool, never heredocs, for doc text |
| CI's Ubuntu unit-test step was cancelled at 10 minutes with no failure output; `test_runners` never reported (PHASE3 §3bp) | On POSIX `test_mutants.kill_tree` killed only the direct child; the test's looping grandchild survived, holding the runner's captured output pipes open, so `run_tests.py` waited forever. Windows (`taskkill /T`) hid it locally | Read which process never reported; traced the pipe holder in code (no local Linux) | POSIX tree kill from a `ps` snapshot; a per-process `--timeout` in `run_tests.py` turns any hang into a failure with output; tests that start trees clean up their descendants |
| A one-off Python edit script turned four source files to CRLF and cut `apply_layout_now` with the code being removed (v0.16.0) | `Path.write_text` translates newlines on Windows; the cut's end marker was one function too far | Rewrote the files as bytes with LF; restored the function from `git show`; ruff's F821 and the suites caught it | In edit scripts use bytes or `newline='\n'`, and diff a marker-based cut before running anything |
| A pushed `ci.yml` was rejected as invalid YAML, so no CI job ran (PHASE3 §3by) | A one-line `run:` value contained `: ` (`'not the CI venv: '`), which YAML reads as a mapping key; actionlint wasn't installed locally, so the edit went out unlinted | Installed actionlint 1.7.12 and reproduced the error; went back to a `run: \|` block | Run actionlint on every workflow edit before committing; put any `run:` holding `: ` in a `\|` block |
| Two `test_workflow` install tests failed locally because the game was open (PHASE3 §3bx) | They ran `install.py` as a child process, which asked the real `tasklist` whether Borderlands was running; CI never has the game open, so only local runs failed | Closed the game and re-ran | Install scenarios run `install.main` in-process with the process query injected; reproduce with a stand-in `Borderlands.exe` (a copied `ping.exe`) |
| Running `test_land` with `GIT_DIR` exported (as a git hook does) set `core.bare=true` on the real repository and switched a worktree's branch to `main` (PHASE3 §3cd) | `test_land` and `test_workflow` run `git init`, `symbolic-ref` and commits in throwaway folders, and `GIT_DIR` made those commands act on the repository named in the variable | `git config core.bare false` and `git switch` back; checked refs, reflog and `git log --all --author=Test` for other damage (none) | Both suites drop the `GIT_*` repository variables in `setUp`; reproduce hook-only failures against a throwaway repository, never the real `GIT_DIR` |
| The mutation command could not start: its baseline failed (PHASE3 §3cc) | `test_mutants.py` ran all of `test_ci.py` in one process, but two cases call the real mod's `main()`, which works once per process; the same cause made `test_original_art_movie_passes_both_suites` look broken when the file was run whole (§3cb). It also never ran `test_hudmovie`/`test_swfmerge`, so builder mutants could not be killed. Nobody had run the command since those cases were added | Ran each case in its own process, added the builder suites, and a test in `test_runners` for both | When a test is added that can only run once per process, check every runner that runs a file whole (`test_mutants.py`, `watchdog_run.py`), not just `run_tests.py`'s per-case list; run the mutation baseline (`test_mutants.py`) after changing the suites |
| Two source patches written as Bash heredoc Python scripts corrupted escapes while writing the new tests (PHASE3 §3cc): `\\n` became a real newline inside a string literal, and `\x00` became raw control bytes, so `grep` called the file "Binary file matches" | The Bash wrapper collapses backslashes inside heredocs (the NUL case in the first session's entry above); a patch that inserts text containing `\` hits it, while one without backslashes worked | Rewrote the affected lines with the Edit tool and a Write-created script file (`raw` strings) | Never put a backslash in a heredoc: use Edit for the change, or Write a `.py` script and run it. After any scripted edit run `git diff --stat`, the tests, and `grep -aP '[\\x00-\\x08]' <file>` (control characters), and keep `newline='\n'` |
