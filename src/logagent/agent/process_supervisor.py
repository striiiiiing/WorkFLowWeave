"""Standalone Linux child reaper, invoked with Python -I for one shell execution."""

import ctypes
import os
import signal
import subprocess
import sys
from pathlib import Path

_PR_SET_CHILD_SUBREAPER = 36
_PR_SET_PDEATHSIG = 1
_EXIT_POLL_SECONDS = 0.05


def supervise(argv):
    # Adoption remains local to this helper; the application is not a global reaper.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(_PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "Cannot enable child subreaper")
    stopped = False

    def stop(signum, frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    parent = os.getppid()
    if libc.prctl(_PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "Cannot link supervisor to parent lifetime")
    if os.getppid() != parent:
        return 128 + signal.SIGTERM
    child = subprocess.Popen(argv, start_new_session=True)
    try:
        while not stopped:
            try:
                code = child.wait(timeout=_EXIT_POLL_SECONDS)
                return code if code >= 0 else 128 - code
            except subprocess.TimeoutExpired:
                continue
        return 128 + signal.SIGTERM
    finally:
        # Once each direct child dies, its remaining descendants are adopted here.
        children_file = Path(f"/proc/self/task/{os.getpid()}/children")
        while True:
            children = [int(value) for value in children_file.read_text().split()]
            if not children:
                break
            for pid in children:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            for pid in children:
                try:
                    os.waitpid(pid, 0)
                except ChildProcessError:
                    pass


if __name__ == "__main__":
    sys.exit(supervise(sys.argv[1:]))
