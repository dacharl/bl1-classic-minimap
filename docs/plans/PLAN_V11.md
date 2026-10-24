# v0.11 plan: optional external performance telemetry (2026-10-24)

**Planning only.** No runtime, build configuration or installed files changed. User requirement:
timing must be optional and removable from the built artifact entirely; prefer a fully external profiler.
This supersedes the initial proposal for timing branches inside the minimap.

## Confirmed decisions from grilling, round 1

The user accepted all four recommendations on 2026-10-24:

1. Primary outcome: attribute elapsed time to minimap operations; assess visible gameplay impact with
   independent frame-time measurements. Synchronous elapsed duration is not a measurement of process
   CPU time and includes time spent waiting inside calls.
2. A separate removable **in-process** profiler add-on is acceptable; the standard artifact remains
   untouched and detachment restores original functions. See [ADR 0001](../adr/0001-keep-profiling-out-of-standard-minimap.md).
3. v0.11 completion includes a working MCP performance provider/adapter in `steam-deck-scripts`, with
   discovery and reader tests. It is part of the implementation scope, not a future compatibility note.
4. A capture starts by explicit action, defaults to 60 seconds, then stops and saves automatically.
   No periodic disk writes during its measurement window. A crash may lose the in-progress run.

## Confirmed decisions from grilling, round 2

The user accepted both recommendations on 2026-10-24:

5. **Exclusive wrapper ownership.** The profiler supports only the case where it is the last wrapper on each
   function it measures. If another mod has replaced one of those functions after the profiler attached,
   detaching cannot remove the profiler's wrapper from that mod's closure. The profiler then reports a
   **detach conflict**, stops measuring, and tells the user to disable the later wrapper or restart the game
   to restore a clean call path. It never claims full detachment in that case and never overwrites the other
   mod's replacement. Coexisting with arbitrary third-party wrappers is not supported. See
   [ADR 0002](../adr/0002-profiler-owns-its-wrappers-exclusively.md).
6. **No hot reload while attached.** No SDK reload notification was found. If the core module object is
   replaced while the profiler is attached, the profiler aborts the capture with an unsupported-lifecycle
   status and removes only the wrappers it still owns. The core's own `State.reset` (HUD replacement, error
   recovery) is not a reload and must not detach the profiler.

## Confirmed decisions from grilling, round 3

The user accepted all four recommendations on 2026-10-24:

7. **Frame-time tools:** PresentMon on Windows and MangoHud on the Steam Deck provide the independent
   frame-time measurements. The in-game validation section names the steps for both.
8. **Overhead targets are release requirements:** under 0.05 ms incremental p95 per admitted update and
   under 64 KiB of collector state, checked by the local benchmark (not CI). If missed, measure fewer
   functions first; add sampling only after that, with sample counts reported.
9. **The profiler's own buttons only:** v0.11 exposes **Start performance capture**, **Dump performance
   report** and **Reset performance statistics** in the MODS menu. F7 stays untouched; no core change and
   no unverified SDK hook to reuse it.
10. **Shipping:** the profiler is a separate build target, tested in CI alongside the core, but excluded
    from the normal release. It is published only as a separate investigation download and never
    installed with a regular update.

## Confirmed decisions from grilling, round 4

The user accepted all four recommendations on 2026-10-24. They rest on how `steam-deck-scripts` discovers
reports today: each provider is an entry in `scripts/games/borderlands-1-goty-classic/tui.json` with a
producer-version allowlist and a `report_root` relative to the game install, and
`src/steam_deck_diagnostics/registry.py:discover` matches a fixed file name per adapter (the existing
`bl1_minimap` adapter also reads `archive/slot-1..6`).

11. **Report history:** before saving, the profiler moves the previous report pair into
    `archive/slot-1..8` (slot 1 newest, slot 8 dropped), so alternating validation runs (at least three
    per condition) are not overwritten. Rotation happens after the capture stops, never during it.
12. **Discovery location:** a new provider entry in `borderlands-1-goty-classic/tui.json`,
    `report_root` = `sdk_mods/settings/classic_minimap_profiler/reports` under the game folder, found by
    the existing install lookup on Windows and the Deck. `registry.discover` needs a small change to match
    the new adapter's file name and archive slots; that is a listed v0.11 task.
13. **Capture length:** a MODS option with 30, 60, 120 or 300 s, default 60. The report records the
    length actually measured.
14. **Supported core versions:** an exact allowlist, starting with v0.10.0. Any other core version is
    refused with an unsupported-version status and no wrappers. The MCP provider keeps its own allowlist
    of profiler versions.

## Confirmed decision, round 5: who builds what

15. **Split ownership along the report file.** This repository builds the profiler add-on and owns the
    performance report contract: a schema document plus fixture reports. `steam-deck-scripts` owns the
    MCP performance adapter and implements it against those fixtures in its own workspace and sessions.
    This repository does not edit `steam-deck-scripts`. The handoff is
    [PLAN_V11_MCP_HANDOFF.md](PLAN_V11_MCP_HANDOFF.md). Decision 3 (a working adapter is part of v0.11
    completion) still holds: v0.11 is complete only when both sides pass their acceptance.

Terminology is recorded in [GLOSSARY.md](../../GLOSSARY.md). This interview is still in progress;
unresolved decisions below are proposals, not permission to begin implementation.

## Architecture decision

Build and ship the normal `classic_minimap.sdkmod` with **no telemetry imports, timers, counters,
configuration branches, callbacks, or wrapper dispatch**. Do not add an Off check to PlayerTick or `cmd`.
Do not change the movie or add profiling commands to its AS2. The standard mod must work independently
of the profiler, with the same hot path whether the profiler exists elsewhere or not.

First prototype a separate, optional `classic_minimap_profiler.sdkmod` that measures only after an explicit
capture action. A normal distribution contains the core artifact alone. A profiling distribution contains that
same core artifact plus the separate profiler. Building the standard artifact must not require profiler
sources or dependencies. Do not bundle the profiler in the core and rely on a runtime flag to disable it.

This is an external PythonSDK add-on running in the game process, not an external OS process. It can
attribute synchronous Python/native calls; a separate frame-time profiler can complement it for actual
frame/render behavior. Neither approach should be described as zero-overhead while recording.

If a necessary measurement cannot be captured externally, document that gap first. Only then consider
a separate opt-in instrumented build, under the fallback described below. Do not silently add production
instrumentation to close the gap.

## Research evidence and feasibility work

The current source supplies useful interception points without editing the core:

- The registered `on_player_tick` handler calls module-global `tick(obj)`. Replacing the module's `tick`
  reference appears sufficient to wrap the body the handler calls, even if replacing the registered
  handler itself would not change the SDK's callback registration. Verify this through the real hook.
- `tick` calls module-global `current_hud_movie`, `start`, `collect`, `capture`, `objective_key`,
  `rebuild_in_place`, `threat_string`, `cmd`, and other functions. They are candidates for reversible
  function wrappers. The callable names alone are not a stable public profiling API; use a tested adapter
  for the supported core version and fail closed for unsupported shapes.
- `tick` throttles work at 0.05 s; epoch/threat checks run at 0.25 s, objective checks at 0.5 s and dock
  checks at 1 s. Count actual executed stages rather than assuming a stage runs on every callback.
- In the present implementation, `current_hud_movie` is called immediately after the tick throttle gate.
  Its entry while a wrapped tick is active is a possible admission signal without an extra scheduler
  clock or engine read. Prototype and test this; if ambiguous, report all tick-call costs and clearly
  state the inability to separate admitted ticks. Do not alter scheduling just for attribution.
- F7 is registered with the SDK and performs additional engine/movie reads. An external wrapper of the
  module's `on_diag_key` may not intercept that registration. The profiler exposes its own MODS
  buttons instead (decision 9); F7 integration is out of scope for v0.11.
- `State.reset` occurs during HUD replacement and error recovery. External aggregates must survive it.
- The existing game stubs invoke the real registered hooks and commands. They can verify whether these
  wrappers see actual calls and preserve behavior before anything is installed in game.

**Lifecycle findings (source-verified 2026-10-24, from the installed `mods_base.sdkmod`; not yet observed
in game):**
- **Enabled state:** the core exports its `mod` object (`sdk_mods/classic_minimap/__init__.py`, end of
  module). `mods_base/mod.py` exposes `is_enabled`, `on_enable` and `on_disable`. `enable()` sets
  `is_enabled`, enables registered callbacks, then calls `on_enable`; `disable()` does the reverse. The
  profiler can read `mod.is_enabled` on the already loaded module, with no engine query.
- **Tick:** `mods_base/hook.py` registers the hook's wrapped function with the SDK, so replacing the
  module's `on_player_tick` does **not** change the registered callback. The registered callback calls
  `tick(obj)` through module globals, so replacing the module's `tick` does. `get_active_count()` checks
  identifier presence, not callback identity.
- **Enable/disable transitions:** `mods_base/mod_factory.py` copies the module's `on_enable`/`on_disable`
  into fields on the `mod` object at build time. To observe transitions, wrap `mod.on_enable`/
  `mod.on_disable` (reversibly, with tests), not the module names.
- **Admitted updates:** `tick` returns at its 0.05 s throttle gate; its next call is `current_hud_movie`.
  Seeing that nested call inside a wrapped tick counts admitted updates without an extra clock or engine
  read. Later early returns (replacement HUD, no pawn) still count as admitted. Classify updates by the
  nested calls observed (`start`, `collect`, `capture`, `rebuild_in_place`) and their outcomes, not by
  `S.phase` at entry alone.
- **Reload:** no SDK reload notification contract was found in the inspected files (decision 6).

These are source-derived opportunities, not measured bottlenecks. There is no runtime timing baseline
yet. Test-suite/mutation-run duration does not measure minimap performance.

The first implementation deliverable is a small feasibility spike in the profiler and its tests:
prove real-hook interception, correct pass-through of values/errors, safe attach/detach and complete
absence from the core artifact. Record which measurements work before expanding the metric set.

## Attach, detach and compatibility

1. Enable the profiler only against an already loaded, enabled supported core. Do not import the core
   just to discover it: that can register/enable things. Resolve it through the existing mod registry or
   loaded modules after checking their actual behavior in this SDK.
2. Store only the original Python callables needed for restoration and plain numeric/context data.
   Never retain engine objects between calls; obey the existing WeakPointer/KEEP_ALIVE rules.
3. Attach once. Wrapper signatures preserve arguments, return values, exceptions and command order.
   Time with a monotonic `perf_counter_ns`, independently injectable from the core scheduler clock.
   Use `finally` to account for failed calls without swallowing the original error.
4. Disable/unload restores the original function objects, removing the wrapper cost entirely, when the
   profiler still owns every wrapped attribute. If any attribute was replaced after attach, report a
   detach conflict (decision 5): restore the attributes still owned, leave the replaced one alone, stop
   measuring, and state that a clean path needs the later wrapper disabled or a restart. Core
   disable/re-enable must not stack wrappers or keep stale references. A replaced core module aborts the
   capture with unsupported-lifecycle status (decision 6).
5. Telemetry failures disable/detach measurement safely and produce one diagnostic warning. They must
   not reset the minimap, mask core errors, or leave a partially attached set of wrappers.
6. Export supported core version and profiler version in every report. Test unsupported-version handling;
   no claim of compatibility with arbitrary future functions or third-party wrappers. Tests cover a later
   third-party wrapper (detach conflict reported, its replacement untouched) and a replaced core module
   (capture aborted, owned wrappers removed).

## Prior MCP diagnostic format: reuse the pattern, not the POC identity

The user identified additional research in `C:/Users/Charles/Dev/steam-deck-scripts`. Read the current
producer/reader code as well as its older specs; version and size limits evolved after those specs.
Relevant sources, relative to that repository:

| Source | Verified relevance |
|---|---|
| `docs/mcp.md`, SDK diagnostics and minimap sections | Provider discovery, report bounds, immutable revisions, explicit unknown live state and paged sections. |
| `docs/superpowers/specs/2026-10-11-bl1-minimap-mcp-evidence.md` | Fixed-name report discovery and content-hash revisions; the original 256 KiB limit describes older POC formats. |
| `docs/superpowers/specs/2026-10-15-mcp-evidence-summary.md` and `src/steam_deck_diagnostics/minimap_bl1.py:evidence_summary` | Derive a small summary after validation: at most 8 KiB, strings capped at 96 characters, fixed-vocabulary notes, missing fields remain null. |
| `src/steam_deck_diagnostics/minimap_bl1.py:read_report`, `bounded_json.py:decode` | Validate exact Classic identity/version, JSON depth, duplicate keys, non-finite values and counts before exposing evidence. Current POC reader accepts larger lifecycle formats under a separate bound. |
| `src/steam_deck_diagnostics/legacy_bl1.py:summarize` | Schema-1 envelope identity and UTC checkpoint validation for the reflection diagnostic. This is a different format from the POC reader. |
| `scripts/games/borderlands-1-goty-classic/minimap/BL1MinimapPOC/runtime.py:checkpoint` | Atomically replace fixed-name JSON/text outputs using a temporary file; preserve explicit partial/error states. |
| `scripts/games/borderlands-1-goty-classic/minimap/BL1MinimapPOC/wireframe.py:TerrainTiming` | Bounded timing history, per-run context, settling and discarded ineligible windows; interval timing remains separate from CPU/GPU work. |

**Compatibility boundary:** the existing `bl1-minimap` provider discovers the POC's own fixed path and
allowlisted producer versions. It does not discover SDK log lines or this profiler's reports. A similar
JSON object is not sufficient for MCP compatibility. Do not write to `BL1MinimapPOC/reports`, spoof its
version, or reuse `bl1-minimap` as this producer's identity. Do not copy game artwork into performance
reports. Current code, not an old design document, defines the existing reader's accepted versions.

A distinct `bl1-classic-minimap-performance` provider and strict adapter in the MCP repository are a
required v0.11 deliverable, owned and implemented there (decision 15, [handoff](PLAN_V11_MCP_HANDOFF.md)),
alongside the separately packaged profiler built here. The profiler itself needs no MCP server
or connection while collecting, and standard core artifacts remain entirely untouched.

### Proposed producer report and saved-file contract

Provide an explicit **Start performance capture** action owned by the optional profiler. Capture length
is a MODS option (30/60/120/300 s, default 60; decision 13); it stops automatically, then saves fixed-name
JSON plus a small readable text summary under `SETTINGS_DIR/classic_minimap_profiler/reports/`, with
filenames `BL1-classic-minimap-performance-report.json` and `BL1-classic-minimap-performance-summary.txt`.
Before saving, rotate the previous pair into `archive/slot-1..8` (decision 11). Save through a temporary
file and atomic replacement. Do not append an unbounded trace or require a keyboard/console to retrieve
evidence. Retain the last good file if publication fails.

The new envelope is a proposal for our own format, not a claim that an existing reader accepts it:

```json
{
  "schema_version": 1,
  "provider_id": "bl1-classic-minimap-performance",
  "game": {"app_id": 8980, "slug": "borderlands-1-goty-classic", "edition": "Borderlands 1 GOTY Classic"},
  "producer": {"name": "classic_minimap_profiler", "version": "<profiler-version>", "core_version": "<core-version>"},
  "capture": {"id": "<capture-id>", "state": "stopped", "started_at_utc": "<UTC-time>", "checkpoint_time": "<UTC-time>", "elapsed_seconds": 60.0, "save_reason": "manual"},
  "summary": {},
  "timings": {},
  "counters": {},
  "context": {},
  "limitations": []
}
```

Specify the complete section schema and accepted state/reason vocabulary during implementation. UTC
fields identify/report checkpoints only; monotonic time measures elapsed durations. Store no absolute
monotonic-clock value as a cross-process timestamp. Missing timestamps stay null; filesystem mtime is
a filesystem observation. A saved `collecting` checkpoint is last-known producer state, not proof the
game or profiler is still live. Include whether a capture is complete, interrupted or partial.

Use a stricter initial report budget than the artwork-heavy POC: at most 256 KiB UTF-8, JSON depth 16,
fixed metric counts and explicit per-section limits; compact summary at most 8 KiB, summary strings at
most 96 characters. Enforce the producer's own bounds before publishing. Reject duplicate fields,
invalid identities/versions, negative counts, non-finite values, overlong strings and unknown shapes in
the future adapter. Encode unavailable numeric values as null, never fabricated zeros. Clearly mark
histogram percentile upper bounds so they are not mistaken for the POC's sample-derived percentiles.

Save automatically after the timed capture stops; no periodic checkpoint writes during measurement.
A crash can lose the current capture, which is an accepted trade-off for avoiding disk disturbance.
An explicit save/dump of a stopped capture may remain available. Track publication duration/count and
preserve it separately from measured work: saving on the game thread can still disturb frames after
capture completion. Do not offer a periodic-checkpoint option in v0.11 without reopening this decision.

The future reader should validate first, derive a compact `performance_summary`, then expose detailed
`timings`, `counters`, `context` and `limitations` sections through existing session/section tools.
Follow the existing bounded paging and complete response-frame limits; do not add a huge bespoke MCP
response. Content SHA-256 identifies immutable checkpoint revisions, including repeated reads of the
same saved data. Preserve unsupported-format and stale/partial states rather than inventing evidence.

Required reader integration acceptance includes producer fixtures plus real MCP-client tests for discovery,
identity/version mismatch, duplicate/non-finite/deep/oversized JSON, missing fields, immutable changed
revisions, bounded summary/paging and unknown live state. Offline fixtures establish parser behavior;
live Deck/Windows collection and transport remain separate verification claims. The concrete tasks for
the MCP repository are in [PLAN_V11_MCP_HANDOFF.md](PLAN_V11_MCP_HANDOFF.md); this repository does not
modify it.

## Measurements obtainable without core instrumentation

Start with function-boundary aggregates; do not promise per-statement attribution.

| Metric | Boundary and limitation |
|---|---|
| Tick-call duration | Wrapped `tick`, including throttle returns. Excludes the outer controller gate and handler exception/logging code; do not label it full PlayerTick hook cost. |
| Admitted / ordinary / rebuild-containing update | Use a verified nested-call admission signal and observed rebuild wrappers. If it cannot be determined reliably, omit these categories and report the limitation. |
| Startup/collection/capture/rebuild | Wrap `start`, `collect`, `capture`, `rebuild_in_place`; separate attempts, results and errors from ordinary updates. |
| Objective/giver work | Wrap `objective_key`, `giver_states`, `script_count` where practical. Query counts from observed calls; no additional mission queries. |
| Threat refresh | Wrap `threat_string` and its existing source-specific helpers. Count emitted entries from already returned data where available; do not scan again. |
| Dock/epoch/visibility/layout | Wrap existing functions; time actual calls and report count. |
| Movie command submission | Wrap `cmd`, grouped by a fixed operation allowlist. This includes string formatting and synchronous SingleArgInvokeS work. It does not isolate those two costs. |
| Existing movie read helpers | Wrap `get_num` / `get_str`; label these as helper calls, not all engine/GFx reads. Direct calls outside helpers are a documented gap. |

Time around `cmd` measures elapsed synchronous work up to return, not deferred Scaleform rendering or GPU
cost. Calling `SingleArgInvokeS` separately or globally monkeypatching Unreal bindings to obtain timing
is outside this first release. Direct `GetVariable*` / `SetVariable*` calls and helper internals remain
unattributed unless safely observable through existing Python boundaries.

All spans are **inclusive**. Nested function durations overlap. Never sum tick/stage/command totals into
an alleged total frame cost. Distinguish a long callback interval from long execution; callback intervals
are not a trustworthy FPS counter and do not prove the mod caused a hitch.

## Bounded collector and reports

- Profiler disabled/not installed: collector and wrappers do not exist in the core; zero telemetry clock
  reads, branches, serialization, file writes or extra engine calls in the core path.
- Profiler enabled: aggregate every observed call initially, with fixed metric names and fixed operation/
  reason allowlists plus `other`. No raw trace list, unbounded per-zone/per-actor dictionary or engine
  references. Nested calls use bounded bookkeeping with an explicit depth limit.
- Per metric: count, failed-call count, total, maximum and fixed histogram. Millisecond upper bounds:
  `0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 250, 1000`, plus overflow.
  Emit exact mean/max and approximate p50/p95/p99 as bucket upper bounds, using rank `ceil(p * count)`.
  Overflow is `>1000 ms`; empty metrics have count zero and null statistics. Do not serialize Infinity.
- Reports include schema version, profiler/core versions, capture ID, elapsed monotonic duration,
  enabled/stopped status, sample counts, scope/limitations and current plain-data context. Historical
  aggregates cover the capture, not necessarily the currently displayed zone.
- Read counts/context only from already computed plain values or observed function arguments/results.
  Additional engine queries for telemetry are out of scope. Do not format diagnostic context per tick.
- Dump on explicit button press to the SDK log as one prefixed JSON record, with concise console
  confirmation through the verified viewport-console path. Capture completion saves automatically as
  defined above; no per-frame/periodic logging or networking during measurement.
  Snapshot before report/console work so reporting does not contaminate gameplay aggregates.
- Reset starts a new capture without rebuilding the map. Dump does not reset. Disable detaches wrappers
  and retains a stopped report until reset/unload; core map resets do not erase the capture.

## Artifact/build requirements

Two independently buildable outputs, not one core artifact with a telemetry switch:

| Distribution | Contents | Required check |
|---|---|---|
| Standard | `classic_minimap.sdkmod` and the existing local movie package when needed | No profiler module, import, dependency, option, timer or hook in the core artifact. |
| Profiling | The exact same core artifact plus `classic_minimap_profiler.sdkmod` | Core SHA-256 unchanged between distributions; profiler is separately removable. |

Build the core once and reuse it in both distributions so archive timestamps cannot obscure the hash
comparison. Independently verify extracted archive content and dependency metadata. A build without the
profiler source tree must still succeed. Keep all game-derived assets local as before.

Per decision 10, the profiler is its own build target: CI builds and tests it alongside the core, but
the normal release workflow publishes only the standard artifact. The profiler is published separately,
labelled for investigation, and no install step adds it with a regular update. The target must not import
the profiler into production. Preserve ordinary build commands and defaults. No runtime version bump
merely for this plan.

## Test-first implementation sequence

1. **Feasibility:** through the real registered tick hook, show the external wrapper observes calls;
   prove return/error pass-through and no extra engine/GFx calls. Drive throttled and admitted paths.
2. **Isolation/lifecycle:** core-only run and archive contain no telemetry; profiling distribution reuses
   identical core bytes. Enable/disable/reload, duplicate enable, missing/unsupported core, failed attach
   rollback and third-party replacement tests. After detach, original callable identity is restored.
3. **Aggregation/report:** independently controlled duration clock. Script 0.1/0.2/0.4 ms calls and expect
   count 3, total 0.7 ms, mean 0.233333 ms, max 0.4 ms, p95 upper bound 0.5 ms. Cover empty, boundary,
   overflow, exceptions, reset, dump without reset, finite JSON and console failure. Assert bounded memory
   over a long synthetic run. Use literal expectations, not a copy of the collector formula.
4. **Attribution:** exercise startup/retries, objective rebuild/F8, giver queries, radar/pawn fallback and
   command submission. A 2 ms tick containing a 0.5 ms command reports inclusive 2 and 0.5 ms, not 2.5 ms
   overall. Verify the admission signal or explicitly reduce the supported report scope.
5. **Overhead:** optional local benchmark through the existing game stubs, with an external measurement
   clock around the full hook. Warm up, alternate attached/detached order and repeat fixed workloads.
   Measure collector/wrapper overhead; do not put elapsed-time assertions in CI. Release requirements
   (decision 8): under 0.05 ms incremental p95 per admitted update and under 64 KiB collector state. If
   missed, measure fewer functions first, then consider explicit sampling with reported sample counts.
   Detached runs must execute the same core callable path as core-only runs.

Use the established real-mod hook/command tests, extended to load the optional add-on against game stubs.
Add strict per-file coverage/mutation gates for shipped profiler Python files and expand repository/
archive checks to cover both packages. Do not lower existing floors or exempt the add-on from tests.
Run both real-movie suites, automatic unit/coverage gates, lint/workflow/repository/archive checks and
the complete configured mutation suite. Movie behavior and bytecode remain unchanged.

## In-game validation

Install only when requested, using the normal game-closed backup and hash verification loop. Verify
core-only play first, then attach/detach the profiler live where the SDK supports it. Check disable fully
removes wrappers, duplicate enable is safe, F8/travel/error recovery preserve useful capture history, and
dumping a report has no persistent effect on map behavior.

Use the same character/mission/options, graphics settings and frame cap. Warm up, then compare at least
three 60-second runs per condition, alternating order: core-only, profiler installed but disabled,
profiler enabled, and detached again. Record route/zone/workload counts and separate startup/travel,
menus and rebuilds from steady play. Use independent frame-time capture to assess actual rendering
impact and correlate hitches; profiler timing alone cannot establish FPS loss or its cause.

Frame-time tools (decision 7): PresentMon on Windows (record `Borderlands.exe` for the same 60 s window,
CSV output) and MangoHud on the Steam Deck (frame-time logging enabled for the same window). Keep each
tool's own output beside the profiler report for that run; the profiler does not read or launch them.

Acceptance: the standard artifact is entirely telemetry-free; disabled/detached add-on leaves original
functions restored; enabled telemetry is bounded and useful; measured overhead and known coverage gaps
are documented. No optimization or speedup claim before an independently compared baseline exists.

## Fallback only if external attribution is insufficient

If specific indispensable spans are inaccessible, stop at a documented measurement-gap decision before
adding core instrumentation. Propose a separate instrumented source/build target with distinct artifact
name/metadata and explicit opt-in packaging. Standard build inputs must remain uninstrumented: prefer
build-time source transformation in ignored scratch output over runtime flags, decorators or imports in
the production module. Add checks proving the standard package has no instrumentation and both variants
pass the same behavior tests. Never install the instrumented variant as an ordinary update by default.

Do not implement this fallback pre-emptively. The external feasibility spike decides whether it is needed.
