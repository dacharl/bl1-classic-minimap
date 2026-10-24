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

## Suggested improvements (ranked)

1. **Release and install tooling.**
   - `tools/release.py`: bump `__version__` and `pyproject.toml` together, run both suites, build the package (`--new-guid`) and `.sdkmod`.
   - `tools/install.py`: refuse while `Borderlands.exe` runs, back up the installed files to `dist/vNNN/`, copy, verify SHA-256, and run the package bulk-data check.
2. **One shared input cache for every checkout and worktree.** `tools/inputs.py` would extract the classic HUD and status-menu movies and the Enhanced HUD from the game installs into a cache outside the repo (e.g. `%LOCALAPPDATA%\bl1-classic-minimap\inputs`, overridable). The build commands would read from there, and backups would go there too.
3. **Fix the GFx ID collision for inspection tools.** Make the `swfdeps.Movie` lookup prefer standard SWF definitions over GFx extension tags, behind a flag, and verify that `swfbuild`'s closure is unchanged byte for byte before switching it on.
4. **Check fake signatures against the packages.** Add a test helper that reads a script function's parameters (including `out`) with `uedis`/`upk`, and asserts each fake's Python signature matches. It would have caught run 12 offline.
5. **In-game self-test (F7 extension).** Exercise each risky SDK call once (giver calls, the `transform.matrix` read-back, radar read) and log pass/fail, so one key press validates new assumptions before a full play-through.
6. **Promote the scratch helpers into `tools/`:**
   - `bulkcheck.py` → `tools/upkcheck.py` (package bulk-data validation);
   - `checklinks.py` → `tools/checklinks.py`;
   - `strrefs.py` (x64 string references) → `tools/strrefs.py`.
7. **Agent shell rules in AGENTS.md:** use the Write tool for scripts (no heredocs with backslashes), the Edit tool for text, literal paths in worktrees, PowerShell when Bash's wrapper fails, and `PYTHONIOENCODING=utf-8`.
8. **Commit per version** on the feature branch once the user approves, so each in-game run maps to a commit and diffs stay reviewable.
