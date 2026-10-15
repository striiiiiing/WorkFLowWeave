"""Run the API and Nginx together while forwarding container shutdown signals."""

from __future__ import annotations

import signal
import subprocess
import time

STOP_REQUESTED = False
APP_UID = 10001


def _request_stop(_signum: int, _frame: object) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True


def _stop(processes: list[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def main() -> int:
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    processes: list[subprocess.Popen[bytes]] = []
    try:
        processes.append(subprocess.Popen(
            ["python", "/opt/workflowweave/bootstrap.py"],
            user=APP_UID,
            group=APP_UID,
        ))
        processes.append(subprocess.Popen(["nginx", "-g", "daemon off;"]))
        while not STOP_REQUESTED:
            for process in processes:
                exit_code = process.poll()
                if exit_code is not None:
                    return exit_code or 1
            time.sleep(0.25)
        return 0
    finally:
        _stop(processes)


if __name__ == "__main__":
    raise SystemExit(main())
