"""Mutation test command: the asset-free core checks and the profiler checks, each in its own process.

Usage: python -B -I tools/test_mutants.py
Both suites import the real core with stubbed SDK modules, which can only happen once per process.

Hang safety. On timeout Cosmic Ray kills this command (its process group on POSIX, only this process on
Windows) and then waits for the output pipe to close, so a suite stuck in a mutant's infinite loop must
die with it, or the worker waits forever. Two full runs stalled that way (PHASE3 §3z):
  * POSIX: suites stay in this command's process group, which Cosmic Ray's killpg covers.
  * Windows: suites run on the base interpreter (not the venv python.exe launcher, which starts its own
    child) inside a job object that kills them when this process ends, however it ends.
  * Both: this command also kills a suite at SUITE_BUDGET (past Cosmic Ray's 20 s timeout, so a real hang
    is still recorded as a timeout), and watchdog_run.py ends a suite stuck in Python code. A loop inside one
    C call holds the GIL, so only the first two layers can stop that.
"""
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUITES = ('test_ci.py', 'test_profiler.py')
SUITE_BUDGET = 25.0            # seconds for all suites together; cosmic-ray.toml timeout is 20


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


def kill_tree(proc):
    if sys.platform == 'win32':
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)], capture_output=True)
    else:
        proc.kill()
    proc.wait()


def main(suites=SUITES, budget=SUITE_BUDGET):
    deadline = time.monotonic() + budget
    wall_deadline = time.time() + budget + 1.0      # the suites' own watchdog, just after this one
    job = kill_on_close_job() if sys.platform == 'win32' else None
    for suite in suites:
        path = Path(suite) if Path(suite).is_absolute() else HERE / suite
        proc = subprocess.Popen([child_python(), '-B', '-I', str(HERE / 'watchdog_run.py'), str(wall_deadline),
                                 str(path)], cwd=HERE.parent)
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
        if code:
            return code
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
