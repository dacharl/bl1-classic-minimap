# Release, installation and diagnostics tools (2026-10-25)

Implemented offline; see PHASE3 §3ah and [TOOLS.md](../TOOLS.md). Runtime and installed versions unchanged.

## Evidence

FRICTION.md ranks manual releases/installs, throwaway diagnostic parsers and cascading version edits
as its first three improvements. PROGRESS.md records the build order and local game inputs. PHASE1.md
records 134 relocated bulk offsets in classic's HUD package. PLAN_V11 and ADR 0001 require the
profiler add-on to remain optional and the standard minimap artifact to contain no telemetry.

The profiler re-exports PROFILER_VERSION from profiler.py. Its fixture generator currently uses a
fixed core version, while the report contract documents the producer version. Version edits must
preserve intentionally invalid fixture cases and regenerate them through the real generator.

## Plan

- CLI tests use temporary repositories, logs and game folders; live installations are never test targets.
- bump_version.py updates both core declarations, profiler declarations and compatibility allowlist,
  regenerates contract fixtures and updates the two contract introductions. Invalid input fails before
  edits; a failed regeneration restores the original files. UTF-8 output has no BOM.
- release.py accepts an explicit input checkout/directory, builds into a new output directory, runs
  both real-movie suites, repacks with a fresh GUID, and writes a SHA-256 manifest only on success.
  Version bumps are explicit; no release is installed automatically.
- install.py validates the manifest and rebuilt package against the original, checks the game process,
  backs up replaced files under a dated version directory, verifies copies, and prints PROGRESS rows.
  The profiler is selected only with --profiler. A dry run validates without modifying the game folder.
- diag.py reads a local or copied SDK log using literal parsing, reports foreign HUD movies, latest
  snapshots/zoom inputs, warning candidates and timestamped map events. Optional settings input adds
  anchor and profiler summaries. It never evaluates log contents as code.

SSH deployment is optional in FRICTION.md and deferred; these tools target local Windows installs
and copied Deck evidence. No runtime version bump or installation is needed for this tooling task.
