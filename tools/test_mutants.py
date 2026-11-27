"""Mutation test command: the asset-free core checks and the profiler checks, each in its own process.

Usage: python -B -I tools/test_mutants.py
Both suites import the real core with stubbed SDK modules, which can only happen once per process.

Hang safety. On timeout Cosmic Ray kills this command (its process group on POSIX, only this process on
Windows) and then waits for the output pipe to close, so a suite stuck in a mutant's infinite loop must
die with it, or the worker waits forever. Two full runs stalled that way (PHASE3 §3z):
  * POSIX: suites stay in this command's process group, which Cosmic Ray's killpg covers.
  * Windows: suites run on the base interpreter (not the venv python.exe launcher, which starts its own
    child) inside a job object that kills them when this process ends, however it ends.
  * Both: this command also kills a suite and all its descendants at SUITE_BUDGET (past Cosmic Ray's 20 s timeout, so a real hang
    is still recorded as a timeout), and watchdog_run.py ends a suite stuck in Python code. A loop inside one
    C call holds the GIL, so only the first two layers can stop that.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PER_CASE_SUITE = 'test_ci.py'   # its cases run the real mod's main(), which works only once per process
OTHER_SUITES = ('test_builder_formats.py', 'test_swfmerge.py', 'test_hudmovie.py', 'test_profiler.py')   # fast ones first: a kill ends the run
SUITE_BUDGET = 25.0            # seconds for all suites together; cosmic-ray.toml timeout is 20
MUTATED_FILE_ENV = 'MINIMAP_MUTATED_FILE'   # set by run_mutations.py's run_item: the file under mutation
PROBE_ENV = 'MINIMAP_SUITE_PROBE'           # measurement: run every suite and append which failed to this file

# Suites that can kill a mutant, per mutated file, the one that kills most first. A name that is not a key here
# (or an unknown mutation) runs everything, so only a measured entry ever skips a suite.
#
# Measured on 2026-11-26 (PHASE3 §3cg): every suite on a sample of each file's mutants (MINIMAP_SUITE_PROBE), then
# kept each suite that killed any of them, most kills first, and dropped the rest. A process costs about 0.7 s, so
# a survivor (which runs its whole list) went from 11 processes to 2 to 7. An entry is a script, 'script::case' or
# 'test_ci.py' for all its cases; re-measure after adding tests or moving code between files.
CI = PER_CASE_SUITE + '::SourceChecks.'
SUITES_BY_FILE = {
    'sdk_mods/classic_minimap/__init__.py': (CI + 'test_mod_without_game_assets', 'test_profiler.py'),
    'tools/build_sdkmod.py': ('test_profiler.py', CI + 'test_sdkmod_archive_layout_and_cache_exclusion'),
    'sdk_mods/classic_minimap/swfmerge.py': ('test_swfmerge.py', 'test_builder_formats.py',
                                              CI + 'test_classic_gradients_keep_their_external_images'),
    'sdk_mods/classic_minimap/hudmovie.py': ('test_hudmovie.py',),
    'sdk_mods/classic_minimap/swfbuild.py': (CI + 'test_original_art_movie_passes_both_suites',
                                              CI + 'test_original_art_is_glyphs_and_our_own_shapes',
                                              'test_hudmovie.py', 'test_swfmerge.py', 'test_builder_formats.py',
                                              'test_profiler.py'),
    # PLAN_BUILDER_SPLIT: provisional (every suite) until the file's list is probed
    'sdk_mods/classic_minimap/swfrecords.py': ('test_builder_formats.py', 'test_swfmerge.py', 'test_hudmovie.py',
                                                'test_profiler.py', PER_CASE_SUITE),
    'sdk_mods/classic_minimap/as2asm.py': ('test_builder_formats.py', 'test_profiler.py'),
    'sdk_mods/classic_minimap/swfdeps.py': ('test_builder_formats.py', 'test_profiler.py', 'test_hudmovie.py'),
    'sdk_mods/classic_minimap/upk.py': ('test_builder_formats.py', 'test_hudmovie.py'),
    'sdk_mods/classic_minimap_profiler/__init__.py': ('test_profiler.py',),
    'sdk_mods/classic_minimap_profiler/profiler.py': ('test_profiler.py',),
}


def case_suites(path=None):
    """'test_ci.py::SourceChecks.test_x' for each test method, so each case gets its own process. The names come
    from the syntax tree: importing the module here would import the code under mutation into this process."""
    import ast
    path = path or HERE / PER_CASE_SUITE
    tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    return tuple(f'{PER_CASE_SUITE}::{cls.name}.{fn.name}' for cls in tree.body if isinstance(cls, ast.ClassDef)
                 for fn in cls.body if isinstance(fn, ast.FunctionDef) and fn.name.startswith('test_'))


def suites_for(mutated_file, table=None):
    """The suites to run for a mutant in `mutated_file` (a path under the project, any separator), in kill order.
    'test_ci.py' in a list stands for its per-case processes. An unlisted or unknown file gets every suite."""
    table = SUITES_BY_FILE if table is None else table
    chosen = table.get(str(mutated_file).replace('\\', '/')) if mutated_file else None
    if chosen is None:
        chosen = OTHER_SUITES + (PER_CASE_SUITE,)
    return tuple(case for suite in chosen for case in (case_suites() if suite == PER_CASE_SUITE else (suite,)))


def child_python():
    """The real interpreter: a venv's python.exe on Windows is a launcher that starts it as a child."""
    return getattr(sys, '_base_executable', None) or sys.executable


def kill_on_close_job():
    """A Windows job object whose processes die when its last handle (held by this process) closes."""
    import ctypes
    from ctypes import wintypes

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in
                    ('ReadOps', 'WriteOps', 'OtherOps', 'ReadBytes', 'WriteBytes', 'OtherBytes')]

    class BasicLimits(ctypes.Structure):
        _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong), ('PerJobUserTimeLimit', ctypes.c_longlong),
                    ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                    ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                    ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD),
                    ('SchedulingClass', wintypes.DWORD)]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [('BasicLimitInformation', BasicLimits), ('IoInfo', IoCounters),
                    ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                    ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]

    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise OSError(ctypes.get_last_error(), 'CreateJobObjectW failed')
    info = ExtendedLimits()
    info.BasicLimitInformation.LimitFlags = 0x2000            # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info)):
        raise OSError(ctypes.get_last_error(), 'SetInformationJobObject failed')   # 9 = extended limits
    return kernel32, job


def process_tree(root, table):
    """PIDs of root and all its descendants, from (pid, ppid) pairs."""
    children = {}
    for pid, ppid in table:
        children.setdefault(ppid, []).append(pid)
    tree, todo = set(), [root]
    while todo:
        pid = todo.pop()
        if pid not in tree:
            tree.add(pid)
            todo += children.get(pid, [])
    return tree


def kill_tree(proc):
    """Kill a suite and everything it started. On POSIX, proc.kill() alone orphaned a looping grandchild, which
    held the caller's output pipes open: the unit-test runner then stalled until CI cancelled it (PHASE3 3bp)."""
    if sys.platform == 'win32':
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)], capture_output=True)
    else:
        import os
        import signal
        listing = subprocess.run(['ps', '-A', '-o', 'pid=,ppid='], capture_output=True, text=True).stdout
        table = [tuple(int(v) for v in line.split()) for line in listing.splitlines() if len(line.split()) == 2]
        for pid in process_tree(proc.pid, table):     # snapshot first, so killed parents can't hide children
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    proc.wait()


def main(suites=None, budget=SUITE_BUDGET):
    suites = suites_for(os.environ.get(MUTATED_FILE_ENV)) if suites is None else suites
    probe = os.environ.get(PROBE_ENV)
    failed = []
    deadline = time.monotonic() + budget
    wall_deadline = time.time() + budget + 1.0      # the suites' own watchdog, just after this one
    job = kill_on_close_job() if sys.platform == 'win32' else None
    for suite in suites:
        script, _, case = str(suite).partition('::')
        path = Path(script) if Path(script).is_absolute() else HERE / script
        proc = subprocess.Popen([child_python(), '-B', '-I', str(HERE / 'watchdog_run.py'), str(wall_deadline),
                                 str(path), *([case] if case else [])], cwd=HERE.parent)
        if job is not None:
            kernel32, handle = job
            import ctypes
            from ctypes import wintypes
            if not kernel32.AssignProcessToJobObject(wintypes.HANDLE(handle), wintypes.HANDLE(int(proc._handle))):
                print(f'{path.name}: could not join the kill-on-close job ({ctypes.get_last_error()})', flush=True)
        try:
            code = proc.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            kill_tree(proc)
            print(f'{path.name}: still running after the {budget:g} s budget; process tree killed', flush=True)
            return 1
        if code and probe:
            failed.append(str(suite))
        elif code:
            return code
    if probe:
        with open(probe, 'a', encoding='utf-8') as log:
            log.write(json.dumps({'file': os.environ.get(MUTATED_FILE_ENV), 'failed': failed}) + '\n')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
