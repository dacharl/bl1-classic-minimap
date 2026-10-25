"""Classic Minimap Profiler: optional performance captures for Classic Minimap (docs/plans/PLAN_V11.md).

For investigation only. The standard Classic Minimap mod contains no timing code; this separate add-on
attaches reversible wrappers to it only while a capture runs (ADR 0001, ADR 0002). Captures start from
the MODS menu, stop after the chosen length, then save a report under
sdk_mods/settings/classic_minimap_profiler/reports/ (schema: docs/plans/PLAN_V11_MCP_HANDOFF.md).
"""
from typing import Any

from mods_base import SETTINGS_DIR, ButtonOption, SpinnerOption, build_mod, get_pc

from .profiler import CAPTURE_SECONDS, Profiler
from .profiler import PROFILER_VERSION as __version__  # noqa: F401  (one version literal: profiler.py)

REPORT_DIR = SETTINGS_DIR / "classic_minimap_profiler" / "reports"


def log(msg: str) -> None:
    print(msg)


def console(msg: str) -> None:
    """Concise confirmation in the in-game console (the path the core's F7 uses)."""
    try:
        get_pc().Player.ViewportClient.ViewportConsole.OutputText(f"[Classic Minimap Profiler] {msg}")
    except Exception:
        pass


PROFILER = Profiler(out_dir=REPORT_DIR, log=log)

START_MESSAGES = {
    "collecting": "capture started",
    "already_collecting": "a capture is already running",
    "core_missing": "Classic Minimap is not loaded; nothing to measure",
    "core_disabled": "enable Classic Minimap first",
    "unsupported_version": "this Classic Minimap version is not supported by this profiler",
}

opt_length = SpinnerOption("Capture length", "60 s", [f"{s} s" for s in CAPTURE_SECONDS],
                           description="How long a capture measures before it stops and saves.")


def on_start(_: Any = None) -> None:
    status = PROFILER.start(int(opt_length.value.split()[0]))
    console(START_MESSAGES.get(status, status))


def on_dump(_: Any = None) -> None:
    report = PROFILER.dump()
    console("report written to the SDK log and the reports folder" if report else "no capture to report yet")


def on_reset(_: Any = None) -> None:
    PROFILER.reset()
    console("statistics reset")


opt_start = ButtonOption("Start performance capture", on_press=on_start,
                         description="Measure the minimap for the chosen length, then save a report.")
opt_dump = ButtonOption("Dump performance report", on_press=on_dump,
                        description="Stop a running capture and save it; write the latest report to the SDK log.")
opt_reset = ButtonOption("Reset performance statistics", on_press=on_reset,
                         description="Discard the current capture without saving.")


def on_disable() -> None:
    if PROFILER.state == "collecting":
        PROFILER.stop("stopped_by_user")


mod = build_mod(options=[opt_length, opt_start, opt_dump, opt_reset])
