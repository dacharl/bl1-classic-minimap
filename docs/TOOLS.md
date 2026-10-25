# Release and diagnostic tools

Run these commands from the task worktree. All tools support `--help` and Python 3.11+.
No command publishes files or installs automatically as part of a build. Game-derived outputs stay local.

## Synchronize versions

```powershell
python -I tools/bump_version.py 0.10.3 --profiler-version 0.1.3 --dry-run
python -I tools/bump_version.py 0.10.3 --profiler-version 0.1.3
```

The core's `__init__.py` and `pyproject.toml`, the profiler's `PROFILER_VERSION` and `pyproject.toml`,
its core compatibility tuple, the contract introductions and all 21 report fixtures update together.
The profiler re-exports its version from `profiler.py`; it has no independent literal in `__init__.py`.
Previous supported core and producer versions remain listed. The real fixture generator preserves
the intentionally invalid cases. Files use UTF-8 without a BOM. If generation fails, original bytes
are restored. `--repo PATH` selects a different checkout. A compatibility-list addition records the
maintainer's decision; it does not prove a new core is safe to profile. Run the profiler tests too.

## Build a release

```powershell
python -I tools/release.py --inputs C:/Users/Charles/Dev/bl1-classic-minimap/dist/phase2 --stock-package C:/Users/Charles/Dev/bl1-classic-minimap/dist/phase1/GfxHUD.orig.upk --output dist/releases/0.10.2
```

Default inputs are this worktree's `dist/phase2/{HUD_classic,status_menu,HUD_enhanced}.gfx` and
`dist/phase1/GfxHUD.orig.upk`. `--inputs` and `--stock-package` make reuse from another checkout
explicit. The classic movie must match the original package. The output directory must not exist.

The tool builds `HUD_minimap.gfx`, runs both real-movie suites, repacks `GfxHUD_Minimap.upk` with a
new GUID, verifies all package bytes against stock reconstruction (including relocated bulk data),
and builds `classic_minimap.sdkmod`. `release.json` records versions, input hashes and artifact
SHA-256 hashes. The completed directory appears only after success; failed stages are cleaned up.

- `--profiler` also builds the separate `classic_minimap_profiler.sdkmod`.
- `--version 0.10.3 --profiler-version 0.1.3` explicitly runs the bump first. These source edits remain
  if a subsequent build fails, so they can be inspected and fixed; no release directory is published.
- `--dry-run` checks inputs and prints the plan without changing versions or building files.

This is the local artifact build. Run source-only quality/coverage checks from CI.md before release;
the release tool does not replace them or run the hour-long mutation campaign.

## Install a release

```powershell
python -I tools/install.py dist/releases/0.10.2 --stock-package C:/Users/Charles/Dev/bl1-classic-minimap/dist/phase1/GfxHUD.orig.upk --dry-run
# Only when installation is wanted, with the game closed:
python -I tools/install.py dist/releases/0.10.2 --stock-package C:/Users/Charles/Dev/bl1-classic-minimap/dist/phase1/GfxHUD.orig.upk
```

The default game is the Steam classic install recorded in PROGRESS.md. Use `--game PATH` for another
local install and `--backups PATH` to override this worktree's `dist/`. Backups must be outside the
game and release directories. Windows uses `tasklist`; POSIX uses `ps`. Process-query failures refuse
installation. The process check runs before backup and again immediately before replacing files.

The installer verifies every manifest hash, archive versions, package relocation and the installed
stock HUD hash before copying. It backs up every selected installed file into
`dist/v<replaced-core-version>-<UTC timestamp>/`, verifying each backup. Missing previous files and
all hashes are recorded in `install.json`. Copies are staged beside their targets, replaced, and
verified again. A copy/verification failure restores replaced files; a restore failure names the
backup for manual recovery. `GfxHUD.upk` is checked but never written. Linked destination paths are
refused. Successful output includes PROGRESS table rows with full SHA-256 hashes.

Use `--profiler` explicitly to install the add-on from a bundle built with `--profiler`. Otherwise any
existing profiler stays untouched. SSH deployment to the Deck is deferred. This task's validation
used fake game folders only; a real install should still be checked in game after it is requested.

## Summarize evidence

```powershell
python -I tools/diag.py
python -I tools/diag.py C:/evidence/unrealsdk.log --last 5 --settings C:/evidence/settings
python -I tools/diag.py C:/evidence/unrealsdk.log --json
```

With no path, diagnostics reads the local Steam install's log and settings. For a copied Proton log,
pass its path and optionally the copied `sdk_mods/settings` directory. `--last N` chooses how many F7
snapshots to show (default 3); `--json` supplies the same evidence as structured data.

The report includes the latest phase/template/live HUD movie, foreign HUD names, F7 zoom-fit points
and raw/fitted/final zoom, map-ready/rebuild events with log timestamps, warning candidates, anchor
counts by frame and the latest anchor measurements, plus the latest profiler text summary. Warning
classification is heuristic because the core's `warn_once` prints at SDK INFO severity. The report
describes saved evidence, not live game state. A named foreign movie is evidence of a HUD replacement;
it does not identify which mod owns that package. Log dictionaries are parsed as literals, never
executed. Truncated records are listed as parse errors; missing GFx numeric values (`inf`/`nan`)
become JSON null. Missing optional settings files are allowed.
