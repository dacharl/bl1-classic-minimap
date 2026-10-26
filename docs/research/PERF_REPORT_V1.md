# Performance report schema v1 (frozen 2026-10-24)

This is the **report contract** of PLAN_V11 decision 15: the file the optional profiler add-on
(`sdk_mods/classic_minimap_profiler`, versions 0.1.0–0.1.9; the fixtures come from 0.1.9; each release only extends the core allowlist) writes and the MCP performance adapter in
`steam-deck-scripts` reads. [PLAN_V11_MCP_HANDOFF.md](../plans/PLAN_V11_MCP_HANDOFF.md) describes the
handoff; this document is the authoritative field list. The fixtures in `tools/fixtures/perf_reports/`
are part of the contract: `valid-*.json` are produced by the real profiler
(`tools/make_perf_fixtures.py`; `tools/test_profiler.py` fails if they drift), and `invalid-*` are each
one rule broken.

Any change is schema version 2 with new fixtures.

## Files

| Item | Value |
|---|---|
| Folder (relative to the game install) | `sdk_mods/settings/classic_minimap_profiler/reports/` |
| Latest report | `BL1-classic-minimap-performance-report.json` |
| Human summary (not part of the contract) | `BL1-classic-minimap-performance-summary.txt` |
| History | `archive/slot-1/` … `archive/slot-8/`, same two names; slot 1 newest |

The producer saves only after a capture stops, writes both files under `.tmp` names, rotates the archive,
then replaces atomically. A failed save keeps the previous report. Readers must still tolerate missing,
partial or unreadable files.

## Global rules

- UTF-8 JSON object, at most **262,144 bytes**, nesting depth at most **16** (the top-level object is
  depth 1).
- No duplicate keys; no NaN or Infinity; every string at most **96** characters.
- Exactly the keys listed below at every level; unknown keys are a format error.
- Numbers are finite. Unknown values are `null`, never a made-up 0.

## Top level

| Key | Type | Value |
|---|---|---|
| `schema_version` | int | `1` |
| `provider_id` | string | `"bl1-classic-minimap-performance"` |
| `game` | object | `{"app_id": 8980, "slug": "borderlands-1-goty-classic", "edition": "Borderlands 1 GOTY Classic"}` exactly |
| `producer` | object | `name` = `"classic_minimap_profiler"`; `version` = profiler version (allowlisted by the reader); `core_version` = Classic Minimap version (string or null) |
| `capture` | object | below |
| `summary` | object | below |
| `timings` | object | one metric record per metric name, all present |
| `counters` | object | below |
| `context` | object | below |
| `limitations` | array | 0–32 codes from the vocabulary, no duplicates |

## capture

| Key | Type | Rule |
|---|---|---|
| `id` | string | 32 lowercase hex characters |
| `state` | string | `stopped` when `save_reason` is `completed` or `stopped_by_user`; otherwise `aborted` |
| `save_reason` | string | `completed`, `stopped_by_user`, `core_disabled`, `detach_conflict`, `unsupported_lifecycle`, `telemetry_error` |
| `complete` | bool | true only for `completed` |
| `started_at_utc`, `checkpoint_time` | string or null | `YYYY-MM-DDTHH:MM:SS.fffZ` (UTC). Identification only, never durations |
| `requested_seconds` | int | 30, 60, 120 or 300 |
| `elapsed_seconds` | number | ≥ 0, monotonic measured length (rounded to 1 µs) |

## Metric record

```
{"count", "failed", "total_ms", "mean_ms", "max_ms", "buckets", "p50_le_ms", "p95_le_ms", "p99_le_ms"}
```

- `count`, `failed`: int ≥ 0, `failed` ≤ `count`.
- `buckets`: exactly 16 ints ≥ 0 summing to `count`. Upper bounds in ms: `0.01, 0.025, 0.05, 0.1, 0.2,
  0.5, 1, 2, 5, 10, 20, 50, 100, 250, 1000`, then overflow (> 1000 ms). A duration equal to a bound falls in
  that bound's bucket.
- `total_ms`, `mean_ms`, `max_ms`: numbers ≥ 0, or null when `count` is 0.
- `p50_le_ms`, `p95_le_ms`, `p99_le_ms`: the upper bound of the bucket holding rank `ceil(p × count / 100)`;
  null when `count` is 0 or the rank lands in overflow. **They are bucket upper bounds, not sample
  percentiles.**
- An empty metric is `count` 0, `failed` 0, all buckets 0 and every `*_ms` null.
- All spans are **inclusive**: nested calls overlap (a tick contains its commands). Never add metrics
  together.

### Metric names (all 24 always present)

| Name | What it times |
|---|---|
| `tick` | every call of the core's `tick` (the PlayerTick hook body), including calls that return at the 0.05 s throttle |
| `tick_admitted` | ticks that passed the throttle (they called `current_hud_movie`) |
| `start`, `collect`, `capture`, `rebuild_in_place` | map startup, collection, capture and in-place rebuilds |
| `objective_key`, `giver_states`, `script_count` | objective-change checks and mission-giver queries |
| `threat_string` | enemy-dot refresh (radar or pawn fallback) |
| `check_dock`, `hidden_reason` | dock check and visibility rules |
| `get_num`, `get_str` | the core's movie read helpers (direct reads elsewhere are not attributed) |
| `cmd.add`, `cmd.clear`, `cmd.scale`, `cmd.iconscale`, `cmd.tick`, `cmd.threats`, `cmd.frame`, `cmd.dock`, `cmd.hud`, `cmd.other` | movie commands by operation (formatting plus the synchronous `SingleArgInvokeS` call; not rendering) |

A metric the capture never saw has `count` 0, and `limitations` then contains `metric_unobserved`.

## counters

| Key | Type |
|---|---|
| `ticks_total`, `ticks_admitted`, `starts`, `captures`, `rebuilds`, `publications` | int ≥ 0 or null |
| `publication_ms_last` | number ≥ 0 or null (duration of the previous save; null before the first) |

`publications` counts saves by this profiler session, including the one that wrote this file.

## context

| Key | Type |
|---|---|
| `map_frame`, `position`, `threat_source`, `dock_mode` | string ≤ 96 or null |
| `zoom_final`, `icon_scale` | number or null |
| `markers` | int or null |
| `rotate` | bool or null |

Plain values read once when the capture stops; no paths, user names or engine object strings.

## summary

| Key | Type |
|---|---|
| `admitted_updates` | int ≥ 0 |
| `admitted_p95_le_ms`, `tick_max_ms`, `worst_metric_max_ms` | number or null |
| `rebuilds` | int ≥ 0 |
| `worst_metric` | a metric name other than `tick`/`tick_admitted`, or null |

The producer's headline. Readers derive their own summary and may cross-check it.

## limitations vocabulary

| Code | Meaning |
|---|---|
| `inclusive_spans` | spans overlap; do not sum them (always present) |
| `no_render_cost` | Scaleform rendering and GPU work are not measured (always present) |
| `no_cpu_time` | durations are elapsed time, not process CPU time (always present) |
| `direct_gfx_reads_unattributed` | movie reads outside `get_num`/`get_str` are not timed (always present) |
| `crash_loses_capture` | a crash during a capture loses it; nothing is written while measuring (always present) |
| `admission_unverified` | reserved: admitted updates could not be separated (not emitted by profiler 0.1.x) |
| `metric_unobserved` | at least one metric has `count` 0 |
| `detach_conflict` | another mod replaced a wrapped function; the capture ended without a clean detach |
| `unsupported_lifecycle` | the core module was reloaded during the capture |
