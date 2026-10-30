# v0.11 handoff: MCP performance adapter for `steam-deck-scripts` (2026-10-24)

**Status: H0 done (2026-10-24, PHASE3 §3z).** The schema is frozen in
[PERF_REPORT_V1.md](../research/PERF_REPORT_V1.md), which supersedes section 4's draft where they differ,
and the fixtures are in `tools/fixtures/perf_reports/` (5 valid, 16 invalid), produced by profiler 0.1.21
(0.1.1 to 0.1.7 only add cores 0.10.1, 0.10.2, 0.12.0, 0.13.0, 0.13.1, 0.14.0 and 0.14.1 to its allowlist; the schema is unchanged, so the provider should
allow 0.1.0, 0.1.1, 0.1.2, 0.1.3, 0.1.4, 0.1.5, 0.1.6, 0.1.7, 0.1.8, 0.1.9, 0.1.10, 0.1.11, 0.1.12, 0.1.13, 0.1.14, 0.1.15, 0.1.16, 0.1.17, 0.1.18, 0.1.19, 0.1.20 and 0.1.21).
The section 9 items are settled: the metric list is the 24 names in PERF_REPORT_V1, and the profiler's
first version is `0.1.0` (current `0.1.21`). H1 and H2 are pending.

This document is the contract between the two repositories for PLAN_V11 decision 15.
This repository (`bl1-classic-minimap`) builds the profiler add-on and owns the report format.
`C:/Users/Charles/Dev/steam-deck-scripts` owns and implements the MCP performance adapter in its own
workspace. Nothing here edits that repository; a session there copies the agreed spec and fixtures in.

Read with: [PLAN_V11.md](PLAN_V11.md) (decisions 1–15), [GLOSSARY.md](../../GLOSSARY.md),
[ADR 0001](../adr/0001-keep-profiling-out-of-standard-minimap.md),
[ADR 0002](../adr/0002-profiler-owns-its-wrappers-exclusively.md).

## 1. Ownership boundary

| | This repository | `steam-deck-scripts` |
|---|---|---|
| Owns | Profiler add-on, report schema v1, fixture reports, producer tests | Provider entry, discovery, reader/validator, summary, MCP sections, MCP client tests |
| Changes | `sdk_mods/classic_minimap_profiler/`, `tools/`, `docs/` | `scripts/games/borderlands-1-goty-classic/tui.json`, `src/steam_deck_diagnostics/`, `tests/`, `docs/` |
| Never touches | the other repository | the minimap or profiler sources; the game install beyond reading report files |

The report file is the only interface. Neither side imports the other's code.

## 2. Sequence and gates

1. **H0 — contract frozen (this repository).** After PLAN_V11's feasibility spike settles which
   measurements work, publish `docs/research/PERF_REPORT_V1.md` (the schema below, finalised) and the
   fixture set in `tools/fixtures/perf_reports/`. A producer test proves the real profiler writes reports
   that match the schema and the `valid-*` fixtures' shape. Tag the commit that freezes the contract.
2. **H1 — adapter built (`steam-deck-scripts`).** A session there implements section 5 against the H0
   fixtures only. No game, Deck or profiler build is needed.
3. **H2 — joint check.** A report saved by the real profiler in game (Windows first, then the Deck) is
   discovered and read through a real MCP client. Recorded on both sides; until then, live collection and
   transport stay unverified claims.

v0.11 is complete only after H2 (decision 3).

## 3. Identity and files

| Item | Value |
|---|---|
| Provider ID | `bl1-classic-minimap-performance` |
| Adapter name (in `tui.json` and code) | `bl1_classic_perf` |
| Game | app 8980, slug `borderlands-1-goty-classic` (existing profile) |
| `report_root` (relative to the game install) | `sdk_mods/settings/classic_minimap_profiler/reports` |
| Latest report | `BL1-classic-minimap-performance-report.json` (+ `BL1-classic-minimap-performance-summary.txt`, human-only; the adapter ignores it) |
| History | `archive/slot-1/` … `archive/slot-8/`, each holding the same pair; slot 1 newest (decision 11) |
| Producer versions | allowlist in the provider entry's `versions`, starting with the first profiler release (proposed `0.1.0`; the profiler versions independently of the core) |
| Evidence level | `possible` until H2, then `verified` |

Producer behaviour the adapter may rely on: saves happen only after a capture stops; the previous pair is
rotated into the archive first; each file is written to a temporary name and atomically replaced. The
adapter must still tolerate a missing, partial or unreadable file (reported as such, never guessed).

## 4. Report schema v1 (to be finalised at H0)

UTF-8 JSON object, at most **256 KiB**, depth at most **16**, no duplicate keys, no NaN/Infinity, every
string at most 96 characters unless stated. Unknown keys are a format error (strict shape).

```
schema_version   1
provider_id      "bl1-classic-minimap-performance"
game             {app_id: 8980, slug: "borderlands-1-goty-classic", edition: "Borderlands 1 GOTY Classic"}
producer         {name: "classic_minimap_profiler", version, core_version}
capture          {id, state, save_reason, complete, started_at_utc, checkpoint_time,
                  requested_seconds, elapsed_seconds}
summary          producer headline (fixed keys, below)
timings          {<metric>: metric record}         fixed metric names
counters         {<name>: integer >= 0 | null}     fixed names
context          {<name>: scalar | null}           fixed names, plain values only
limitations      [code, ...]                       fixed vocabulary, at most 32
```

**capture:**
- `id`: 32 lowercase hex characters, unique per capture.
- `state`: `stopped` | `aborted`.
- `save_reason`: `completed` (timer ran out) | `stopped_by_user` | `core_disabled` | `detach_conflict` |
  `unsupported_lifecycle` | `telemetry_error`. `state` is `stopped` only for the first two.
- `complete`: true only for `completed`.
- `started_at_utc`, `checkpoint_time`: ISO 8601 UTC (`YYYY-MM-DDTHH:MM:SS.fffZ`) or null. They identify the
  capture; they are not used for durations.
- `requested_seconds`: one of 30, 60, 120, 300 (decision 13). `elapsed_seconds`: monotonic measured
  length, finite, ≥ 0.

**Metric record** (one per fixed metric name):
```
{count, failed, total_ms, mean_ms, max_ms, buckets, p50_le_ms, p95_le_ms, p99_le_ms}
```
- `count`, `failed`: integers ≥ 0, `failed` ≤ `count`.
- `buckets`: exactly 16 integers ≥ 0 summing to `count`, for upper bounds (ms)
  `0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 250, 1000` plus overflow (> 1000 ms).
- `p50_le_ms`/`p95_le_ms`/`p99_le_ms`: the bucket **upper bound** containing rank `ceil(p × count)`
  (`null` for overflow and for empty metrics). They are bounds, not sample percentiles; the adapter must
  label them so.
- Empty metric: `count` 0, `failed` 0, `buckets` all 0, every `*_ms` null.
- All spans are inclusive and overlap; the adapter must never add them together.

**Metric names (proposed; H0 fixes the final list after the spike):** `tick`, `tick_admitted`, `start`,
`collect`, `capture`, `rebuild_in_place`, `objective_key`, `giver_states`, `script_count`,
`threat_string`, `check_dock`, `hidden_reason`, `get_num`, `get_str`, and `cmd.<op>` for the movie
commands `add`, `clear`, `scale`, `iconscale`, `tick`, `threats`, `frame`, `dock`, `hud`, plus
`cmd.other`. A metric the producer could not observe is present with `count` 0 and a matching
limitation code.

**counters:** `ticks_total`, `ticks_admitted`, `starts`, `captures`, `rebuilds`, `publications`,
`publication_ms_last` (this is a duration in ms, finite; the only non-integer counter) — `null` when
unknown, never a fabricated 0.

**context:** `map_frame`, `zoom_final`, `icon_scale`, `position`, `threat_source`, `markers`,
`dock_mode`, `rotate`. Strings ≤ 96 characters; numbers finite; null when unknown. No paths, user names
or engine object strings.

**summary (producer headline):** `admitted_updates`, `admitted_p95_le_ms`, `tick_max_ms`,
`rebuilds`, `worst_metric` (a metric name or null), `worst_metric_max_ms`. The adapter re-derives its own
compact summary and may cross-check these.

**limitations vocabulary (initial):** `inclusive_spans`, `no_render_cost`, `no_cpu_time`,
`admission_unverified`, `direct_gfx_reads_unattributed`, `crash_loses_capture`, `metric_unobserved`,
`detach_conflict`, `unsupported_lifecycle`. H0 may add codes; the adapter rejects unknown ones under v1.

## 5. Tasks in `steam-deck-scripts` (H1)

Concrete starting points, verified against that repository on 2026-10-24 (`f212d5b`):

1. **Spec copy.** Add `docs/superpowers/specs/<date>-bl1-classic-minimap-performance.md` pointing to the
   frozen H0 commit of this repository, and copy the fixtures (they contain no game data) into
   `tests/diagnostics/fixtures/perf_bl1/`.
2. **Provider entry.** Add to `scripts/games/borderlands-1-goty-classic/tui.json` diagnostics:
   `{"id": "bl1-classic-minimap-performance", "adapter": "bl1_classic_perf", "versions": [<profiler
   versions>], "report_root": "sdk_mods/settings/classic_minimap_profiler/reports", "evidence": "possible"}`.
3. **Adapter allowlist.** `src/steam_deck_diagnostics/models.py`: accept `bl1_classic_perf` in the adapter
   set (currently `{"bl1_map", "bl1_minimap", "bl1_native"}`).
4. **Discovery.** `src/steam_deck_diagnostics/registry.py:discover`: for `bl1_classic_perf`, match only
   `BL1-classic-minimap-performance-report.json` in `report_root` plus `archive/slot-1..8/` (same
   symlink/regular-file checks as the `bl1_minimap` branch), and give it its own discovery limit.
   `describe()` should report its kind as an SDK report.
5. **Reader.** New `src/steam_deck_diagnostics/perf_bl1.py`: read with the existing `bounded_json.decode`
   (256 KiB, depth 16), validate section 4 exactly (identity, provider ID, version allowlist, vocabularies,
   bucket sums, `failed` ≤ `count`, finite numbers, string lengths, no unknown keys), then build the
   archive/revision shape `cache.ingest` expects. Revision = SHA-256 of the file bytes.
6. **Summary.** Derive `performance_summary` (≤ 8 KiB, strings ≤ 96, fixed-vocabulary notes, missing
   values null), following `minimap_bl1.py:evidence_summary`. Include capture state/reason/complete,
   requested vs elapsed seconds, admitted updates, the top metrics by `max_ms`, and the limitations. Label
   percentile fields as bucket upper bounds.
7. **Ingest dispatch.** `src/steam_deck_diagnostics/cache.py:ingest`: add the `bl1_classic_perf` branch.
   Unsupported formats keep `format_status` other than `readable`, as today.
8. **Sections.** Expose `timings`, `counters`, `context`, `limitations` through the existing session/section
   and paging tools; no new oversized MCP response.
9. **Docs.** `docs/mcp.md` (provider, bounds, semantics) and the BL1 classic game doc.

## 6. Acceptance tests (H1)

Fixture-driven, in `tests/diagnostics/` and `tests/mcp/`:
- **Discovery:** latest file plus archive slots found; other names ignored; symlinked root, file or slot
  rejected; limit enforced.
- **Validation (one fixture each, all rejected or marked unsupported):** wrong `provider_id`; wrong game
  identity; producer version not allowlisted; `schema_version` 2; duplicate key; NaN/Infinity; depth 17;
  oversized (> 256 KiB); string of 97 characters; unknown key; bucket sum ≠ `count`; `failed` > `count`;
  negative counter; unknown limitation code; `state`/`save_reason` mismatch; missing required field.
- **Valid fixtures read:** `valid-completed` (60 s, populated), `valid-empty-metrics` (null statistics stay
  null), `valid-aborted-detach-conflict`, `valid-overflow` (p99 null, overflow bucket counted),
  `valid-120s`.
- **Revisions:** the same bytes read twice give the same revision; changed bytes give a new immutable one.
- **Summary:** within 8 KiB; percentiles labelled as upper bounds; spans not summed; missing values null.
- **Live state:** a saved report never claims the game or profiler is running.
- **MCP client end-to-end:** discovery → summary → paged sections through the real server, like
  `tests/mcp/test_minimap_evidence.py`.

## 7. Changes after H0

- Adding a profiler version: the producer bumps its version here; the provider's `versions` list is
  updated there. Until then the adapter reports the new reports as unsupported, which is correct.
- Any schema change is `schema_version` 2 with new fixtures and a new H0-style freeze; v1 readers keep
  rejecting v2.
- Disagreements are resolved in this document first, then in both repositories.

## 8. Out of scope

- Reading PresentMon/MangoHud output (decision 7 keeps those as separate files).
- Live collection, starting captures, or any write from the MCP side.
- The existing `bl1-minimap` POC provider: unchanged; this provider never reuses its identity or folders.

## 9. Open until H0

- The final metric list and limitation codes (after the feasibility spike).
- The profiler's first version number (proposed `0.1.0`).
