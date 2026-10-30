"""Capture engine of the optional Classic Minimap profiler (docs/plans/PLAN_V11.md).

No unrealsdk or mods_base imports: the SDK glue lives in __init__.py, so this file is testable on its own.

A capture attaches reversible wrappers to module-level functions of the already loaded core
(`classic_minimap`), times every call with a monotonic clock, and detaches when it stops. Outside a capture
the core runs its own functions untouched (ADR 0001). The profiler must be the last wrapper on each
function: if another mod replaced one after attach, stop reports a detach conflict and leaves that
replacement alone (ADR 0002). Reports follow schema v1 in docs/plans/PLAN_V11_MCP_HANDOFF.md section 4.
"""
import json
import math
from bisect import bisect_left
import os
import shutil
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

PROFILER_VERSION = "0.1.19"
SUPPORTED_CORE_VERSIONS = ("0.10.0", "0.10.1", "0.10.2", "0.12.0", "0.13.0", "0.13.1", "0.14.0", "0.14.1", "0.14.2", "0.14.3", "0.14.4", "0.14.5", "0.14.6", "0.14.7", "0.14.8", "0.15.0", "0.15.1", "0.15.2", "0.15.3", "0.15.4",)   # wrapper targets are these cores' function names (decision 14)
CORE_MODULE = "classic_minimap"
CAPTURE_SECONDS = (30, 60, 120, 300)    # decision 13

PROVIDER_ID = "bl1-classic-minimap-performance"
GAME = {"app_id": 8980, "slug": "borderlands-1-goty-classic", "edition": "Borderlands 1 GOTY Classic"}
REPORT_NAME = "BL1-classic-minimap-performance-report.json"
SUMMARY_NAME = "BL1-classic-minimap-performance-summary.txt"
ARCHIVE_SLOTS = 8                       # decision 11
REPORT_LIMIT = 256 * 1024
TEXT_LIMIT = 96
LOG_PREFIX = "[Classic Minimap Profiler] report "
MAX_DEPTH = 32

# Bucket upper bounds in ns (0.01 ms ... 1000 ms) plus one overflow bucket.
BOUNDS_NS = (10_000, 25_000, 50_000, 100_000, 200_000, 500_000, 1_000_000, 2_000_000, 5_000_000,
             10_000_000, 20_000_000, 50_000_000, 100_000_000, 250_000_000, 1_000_000_000)
BOUNDS_MS = tuple(b / 1_000_000 for b in BOUNDS_NS)

CMD_OPS = ("add", "clear", "scale", "iconscale", "tick", "threats", "frame", "dock", "hud")
TIMED = ("start", "collect", "capture", "rebuild_in_place", "objective_key", "giver_states", "script_count",
         "threat_string", "check_dock", "hidden_reason", "get_num", "get_str")
# tick and cmd get their own wrappers; current_hud_movie is wrapped only as the admission signal: tick's
# next call after its throttle gate (PLAN_V11 lifecycle findings).
WRAPPED = ("tick", "current_hud_movie", "cmd") + TIMED
METRICS = ("tick", "tick_admitted") + TIMED + tuple("cmd." + op for op in CMD_OPS) + ("cmd.other",)

STANDING_LIMITATIONS = ("inclusive_spans", "no_render_cost", "no_cpu_time", "direct_gfx_reads_unattributed",
                        "crash_loses_capture")
LIMITATIONS = STANDING_LIMITATIONS + ("admission_unverified", "metric_unobserved", "detach_conflict",
                                      "unsupported_lifecycle")
REASONS = ("completed", "stopped_by_user", "core_disabled", "detach_conflict", "unsupported_lifecycle",
           "telemetry_error")


def utc_now() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


class Stats:
    """Count, failures, total, max and a fixed histogram for one metric."""

    __slots__ = ("count", "failed", "total_ns", "max_ns", "buckets")

    def __init__(self) -> None:
        self.count = self.failed = self.total_ns = self.max_ns = 0
        self.buckets = [0] * (len(BOUNDS_NS) + 1)

    def record(self, ns: int, ok: bool) -> None:
        self.count += 1
        if not ok:
            self.failed += 1
        self.total_ns += ns
        if ns > self.max_ns:
            self.max_ns = ns
        self.buckets[bisect_left(BOUNDS_NS, ns)] += 1   # first bound >= ns; past the last = overflow

    def upper_bound(self, percent: int) -> Optional[float]:
        """Upper bound (ms) of the bucket holding rank ceil(percent/100 * count); None for overflow."""
        rank = -(-percent * self.count // 100)
        seen = 0
        for i, n in enumerate(self.buckets):
            seen += n
            if seen >= rank:
                return BOUNDS_MS[i] if i < len(BOUNDS_MS) else None
        return None

    def as_dict(self) -> dict[str, Any]:
        empty = self.count == 0
        return {"count": self.count, "failed": self.failed,
                "total_ms": None if empty else self.total_ns / 1_000_000,
                "mean_ms": None if empty else self.total_ns / self.count / 1_000_000,
                "max_ms": None if empty else self.max_ns / 1_000_000,
                "buckets": list(self.buckets),
                "p50_le_ms": None if empty else self.upper_bound(50),
                "p95_le_ms": None if empty else self.upper_bound(95),
                "p99_le_ms": None if empty else self.upper_bound(99)}


def serialize(report: dict[str, Any]) -> str:
    """The saved file's exact text (fixtures use it too). Refuses NaN/Infinity."""
    return json.dumps(report, allow_nan=False, indent=1)


def _text(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else None
    return str(value)[:TEXT_LIMIT]


class Profiler:
    def __init__(self, out_dir: Path, log: Callable[[str], None] = print,
                 clock: Callable[[], int] = time.perf_counter_ns, utc: Callable[[], str] = utc_now,
                 new_id: Callable[[], str] = lambda: uuid.uuid4().hex, modules: Optional[dict] = None) -> None:
        self.out_dir, self.log, self.clock, self.utc, self.new_id = Path(out_dir), log, clock, utc, new_id
        self.modules = sys.modules if modules is None else modules
        self.state = "idle"                  # idle | collecting | stopped
        self.report: Optional[dict[str, Any]] = None
        self.conflicts: list[str] = []
        self.publications = 0
        self.publication_ms_last: Optional[float] = None
        self.stats: Any = None
        self.core: Any = None
        self._owned: dict[str, tuple[Any, Any]] = {}   # name -> (original, wrapper)
        self._owned_disable: Optional[tuple[Any, Any, Any]] = None   # (mod object, original, wrapper)
        self._core_mod: Any = None
        self._admitted = False
        self._depth = 0
        self._failed = False

    # ---- lifecycle ---------------------------------------------------------------------------------

    def start(self, seconds: int) -> str:
        if self.state == "collecting":
            return "already_collecting"
        if seconds not in CAPTURE_SECONDS:
            raise ValueError(f"capture length must be one of {CAPTURE_SECONDS}")
        core = self.modules.get(CORE_MODULE)
        if core is None:
            return "core_missing"
        if getattr(core, "__version__", None) not in SUPPORTED_CORE_VERSIONS:
            return "unsupported_version"
        if not getattr(getattr(core, "mod", None), "is_enabled", False):
            return "core_disabled"
        self.core, self.conflicts, self._failed, self._depth = core, [], False, 0
        self.stats = {name: Stats() for name in METRICS}
        self.ticks_total = self.ticks_admitted = 0
        self.capture_id = self.new_id()
        self.started_utc = self.utc()
        self.requested = seconds
        self.t0 = self.clock()
        self.deadline = self.t0 + seconds * 1_000_000_000
        self.report = None
        for name in WRAPPED:
            original = getattr(core, name)
            wrapper = self._wrap(name, original)
            setattr(core, name, wrapper)
            self._owned[name] = (original, wrapper)
        mod = self._core_mod = core.mod
        original_disable = getattr(mod, "on_disable", None)
        if original_disable is not None:
            def on_disable(*args: Any, **kwargs: Any) -> Any:
                self.stop("core_disabled")
                return original_disable(*args, **kwargs)
            mod.on_disable = on_disable
            self._owned_disable = (mod, original_disable, on_disable)
        self.state = "collecting"
        return "collecting"

    def stop(self, reason: str) -> Optional[dict[str, Any]]:
        if self.state != "collecting":
            return self.report
        elapsed_ns = self.clock() - self.t0
        # A replaced module, or importlib.reload re-running it in place (build_mod makes a new mod object).
        if self.modules.get(CORE_MODULE) is not self.core or getattr(self.core, "mod", None) is not self._core_mod:
            reason = "unsupported_lifecycle"
        self._detach()
        if self.conflicts and reason not in ("unsupported_lifecycle", "telemetry_error"):
            reason = "detach_conflict"
        if self.conflicts:
            self.log(f"[Classic Minimap Profiler] another mod replaced {', '.join(self.conflicts)} after the "
                     "capture started; its wrapper still calls the profiler's. Disable that mod or restart the "
                     "game to restore a clean call path.")
        self.state = "stopped"
        self.report = self._build(reason, elapsed_ns)
        self._publish(self.report)
        cap = self.report["capture"]
        self.log(f"[Classic Minimap Profiler] capture {cap['state']} ({cap['save_reason']}) after "
                 f"{cap['elapsed_seconds']:.1f} s")
        return self.report

    def dump(self) -> Optional[dict[str, Any]]:
        report = self.stop("stopped_by_user") if self.state == "collecting" else self.report
        if report is None:
            self.log("[Classic Minimap Profiler] no capture to report yet")
            return None
        self.log(LOG_PREFIX + json.dumps(report, allow_nan=False, separators=(",", ":")))
        return report

    def reset(self) -> None:
        if self.state == "collecting":
            self._detach()
        self.state, self.report, self.stats = "idle", None, None

    def _detach(self) -> None:
        for name, (original, wrapper) in self._owned.items():
            if getattr(self.core, name, None) is wrapper:
                setattr(self.core, name, original)
            else:
                self.conflicts.append(name)
        self._owned = {}
        if self._owned_disable is not None:
            mod, original, wrapper = self._owned_disable
            if getattr(mod, "on_disable", None) is wrapper:
                mod.on_disable = original
            else:
                self.conflicts.append("mod.on_disable")
            self._owned_disable = None

    def _telemetry_failure(self, ex: BaseException) -> None:
        if not self._failed:
            self._failed = True
            self.log(f"[Classic Minimap Profiler] telemetry failed ({type(ex).__name__}: {ex}); "
                     "measurement stopped, the minimap is unaffected")
        if self.state == "collecting":
            try:
                self.stop("telemetry_error")
            except Exception:                 # never let reporting break the game loop
                self.state = "stopped"

    # ---- wrappers ----------------------------------------------------------------------------------

    def _record(self, key: str, ns: int, ok: bool) -> None:
        if self.state != "collecting":
            return
        try:
            self.stats[key].record(ns, ok)
        except Exception as ex:
            self._telemetry_failure(ex)

    def _wrap(self, name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
        prof = self
        if name == "current_hud_movie":
            def admitted(*args: Any, **kwargs: Any) -> Any:
                prof._admitted = True
                return fn(*args, **kwargs)
            return admitted
        if name == "tick":
            def tick(*args: Any, **kwargs: Any) -> Any:
                prof._admitted = False
                t0 = prof.clock()
                ok = False
                try:
                    result = fn(*args, **kwargs)
                    ok = True
                    return result
                finally:
                    prof._after_tick(prof.clock() - t0, ok)
            return tick
        if name == "cmd":
            def cmd(movie: Any, op: str, *args: Any) -> Any:
                return prof._timed("cmd." + op if op in CMD_OPS else "cmd.other", fn, (movie, op) + args, {})
            return cmd

        def timed(*args: Any, **kwargs: Any) -> Any:
            return prof._timed(name, fn, args, kwargs)
        return timed

    def _timed(self, key: str, fn: Callable[..., Any], args: tuple, kwargs: dict) -> Any:
        if self._depth >= MAX_DEPTH:
            return fn(*args, **kwargs)
        self._depth += 1
        t0 = self.clock()
        ok = False
        try:
            result = fn(*args, **kwargs)
            ok = True
            return result
        finally:
            self._depth -= 1
            self._record(key, self.clock() - t0, ok)

    def _after_tick(self, ns: int, ok: bool) -> None:
        if self.state != "collecting":
            return
        try:
            self.stats["tick"].record(ns, ok)
            self.ticks_total += 1
            if self._admitted:
                self.stats["tick_admitted"].record(ns, ok)
                self.ticks_admitted += 1
        except Exception as ex:
            self._telemetry_failure(ex)
            return
        if self.clock() >= self.deadline:
            self.stop("completed")

    # ---- report ------------------------------------------------------------------------------------

    def _context(self) -> dict[str, Any]:
        core = self.core
        readers = {"map_frame": lambda: core.S.anchor.get("MapFrame"), "zoom_final": lambda: core.zoom_percent(),
                   "icon_scale": lambda: core.icon_percent(), "position": lambda: core.opt_position.value,
                   "threat_source": lambda: core.S.threat_source, "markers": lambda: len(core.S.marks),
                   "dock_mode": lambda: core.S.dock_mode, "rotate": lambda: core.opt_rotate.value}
        out = {}
        for key, read in readers.items():
            try:
                out[key] = _text(read())
            except Exception:
                out[key] = None
        return out

    def _build(self, reason: str, elapsed_ns: int) -> dict[str, Any]:
        stats = self.stats if isinstance(self.stats, dict) else {name: Stats() for name in METRICS}
        timings = {name: stats[name].as_dict() for name in METRICS}
        limitations = list(STANDING_LIMITATIONS)
        if any(t["count"] == 0 for t in timings.values()):
            limitations.append("metric_unobserved")
        if reason in ("detach_conflict", "unsupported_lifecycle"):
            limitations.append(reason)
        worst = max((n for n in METRICS if n not in ("tick", "tick_admitted") and timings[n]["count"]),
                    key=lambda n: timings[n]["max_ms"], default=None)
        admitted = timings["tick_admitted"]
        state = "stopped" if reason in ("completed", "stopped_by_user") else "aborted"
        return {
            "schema_version": 1,
            "provider_id": PROVIDER_ID,
            "game": dict(GAME),
            "producer": {"name": "classic_minimap_profiler", "version": PROFILER_VERSION,
                         "core_version": _text(getattr(self.core, "__version__", None))},
            "capture": {"id": self.capture_id, "state": state, "save_reason": reason,
                        "complete": reason == "completed", "started_at_utc": self.started_utc,
                        "checkpoint_time": self.utc(), "requested_seconds": self.requested,
                        "elapsed_seconds": round(max(elapsed_ns, 0) / 1_000_000_000, 6)},
            "summary": {"admitted_updates": admitted["count"], "admitted_p95_le_ms": admitted["p95_le_ms"],
                        "tick_max_ms": timings["tick"]["max_ms"], "rebuilds": timings["rebuild_in_place"]["count"],
                        "worst_metric": worst,
                        "worst_metric_max_ms": None if worst is None else timings[worst]["max_ms"]},
            "timings": timings,
            "counters": {"ticks_total": self.ticks_total, "ticks_admitted": self.ticks_admitted,
                         "starts": timings["start"]["count"], "captures": timings["capture"]["count"],
                         "rebuilds": timings["rebuild_in_place"]["count"], "publications": self.publications + 1,
                         "publication_ms_last": self.publication_ms_last},
            "context": self._context(),
            "limitations": limitations,
        }

    def summary_text(self, report: dict[str, Any]) -> str:
        cap, summary = report["capture"], report["summary"]
        lines = [f"Classic Minimap performance capture {cap['id']}",
                 f"state: {cap['state']} ({cap['save_reason']}), {cap['elapsed_seconds']:.1f} of "
                 f"{cap['requested_seconds']} s, core {report['producer']['core_version']}",
                 f"admitted updates: {summary['admitted_updates']} (p95 <= {summary['admitted_p95_le_ms']} ms), "
                 f"slowest tick {summary['tick_max_ms']} ms",
                 "spans are inclusive and overlap; percentiles are bucket upper bounds"]
        for name in METRICS:
            t = report["timings"][name]
            if t["count"]:
                lines.append(f"  {name}: n={t['count']} mean={t['mean_ms']:.4f} ms max={t['max_ms']:.4f} ms "
                             f"p95<={t['p95_le_ms']} failed={t['failed']}")
        return "\n".join(lines) + "\n"

    def write_text(self, path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")

    def _publish(self, report: dict[str, Any]) -> None:
        """Write both files to temporary names, rotate the archive, then atomically replace. A failure
        before the replace keeps the last good report."""
        t0 = self.clock()
        out = self.out_dir
        tmp_report, tmp_summary = out / (REPORT_NAME + ".tmp"), out / (SUMMARY_NAME + ".tmp")
        try:
            data = serialize(report)
            if len(data.encode("utf-8")) > REPORT_LIMIT:
                raise ValueError(f"report exceeds {REPORT_LIMIT} bytes")
            out.mkdir(parents=True, exist_ok=True)
            self.write_text(tmp_report, data)
            self.write_text(tmp_summary, self.summary_text(report))
            self._rotate()
            os.replace(tmp_report, out / REPORT_NAME)
            os.replace(tmp_summary, out / SUMMARY_NAME)
        except (OSError, ValueError) as ex:
            for tmp in (tmp_report, tmp_summary):
                try:
                    tmp.unlink()
                except OSError:
                    pass
            self.log(f"[Classic Minimap Profiler] performance report not saved ({type(ex).__name__}: {ex}); "
                     "the previous report is kept")
            return
        self.publications += 1
        self.publication_ms_last = (self.clock() - t0) / 1_000_000

    def _rotate(self) -> None:
        out = self.out_dir
        if not (out / REPORT_NAME).exists():
            return
        archive = out / "archive"
        oldest = archive / f"slot-{ARCHIVE_SLOTS}"
        if oldest.exists():
            shutil.rmtree(oldest)
        for i in range(ARCHIVE_SLOTS - 1, 0, -1):
            slot = archive / f"slot-{i}"
            if slot.exists():
                os.replace(slot, archive / f"slot-{i + 1}")
        newest = archive / "slot-1"
        newest.mkdir(parents=True)
        for name in (REPORT_NAME, SUMMARY_NAME):
            if (out / name).exists():
                os.replace(out / name, newest / name)
