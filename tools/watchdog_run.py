"""Run a test script as __main__ with an in-process watchdog: past an absolute deadline the process exits.

Usage: python -B -I tools/watchdog_run.py <deadline: time.time() seconds> <script.py>

Used by test_mutants.py. With a venv, Cosmic Ray's timeout kills the python.exe launcher, which also ends
test_mutants (the launcher's job object) but not the suite it started; a suite stuck in a mutant's
infinite loop then held Cosmic Ray's output pipe forever. The watchdog makes every suite end itself.
"""
import os
import runpy
import sys
import threading
import time

TIMED_OUT = 3


def watchdog(deadline):
    time.sleep(max(0.0, deadline - time.time()))
    sys.stderr.write('watchdog: deadline passed; exiting\n')
    sys.stderr.flush()
    os._exit(TIMED_OUT)


def main():
    deadline, script = float(sys.argv[1]), sys.argv[2]
    threading.Thread(target=watchdog, args=(deadline,), daemon=True).start()
    sys.argv = [script]
    sys.path.insert(0, os.path.dirname(os.path.abspath(script)))
    runpy.run_path(script, run_name='__main__')


if __name__ == '__main__':
    main()
