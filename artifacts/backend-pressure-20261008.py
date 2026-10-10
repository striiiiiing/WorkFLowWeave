"""Read-only, rate-limited measurement of an existing backend on myserver.

One dedicated thread and persistent connection per client; real elapsed time
includes draining outstanding requests. CPU 100% means one logical core. RSS
samples cover only the backend process; historical VmHWM is not a stage peak.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import http.client
import json
import math
import os
import platform
import re
import subprocess
import threading
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

HOST = "127.0.0.1"
PORT = 4300
ROUTES = ("/api/health", "/api/sources", "/api/plugins")


def process_pid() -> int:
    sockets = subprocess.check_output(
        ["ss", "-ltnp", f"sport = :{PORT}"], text=True,
    )
    matches = re.findall(r'"workflowweave",pid=(\d+)', sockets)
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one backend listener: {sockets}")
    return int(matches[0])


def cpu_ticks(pid: int) -> int:
    stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return int(stat[11]) + int(stat[12])


def snapshot(pid: int) -> dict:
    memory = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        memory[key] = int(value.split()[0]) * 1024
    status = {}
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        key, value = line.split(":", 1)
        if key in {"VmRSS", "VmHWM", "VmSwap"}:
            status[key] = int(value.split()[0]) * 1024
    return {
        "monotonic": time.monotonic(),
        "backend_cpu_ticks": cpu_ticks(pid),
        "generator_cpu_ticks": cpu_ticks(os.getpid()),
        "backend_rss_bytes": status["VmRSS"],
        "backend_historical_hwm_bytes": status["VmHWM"],
        "backend_swap_bytes": status["VmSwap"],
        "host_available_bytes": memory["MemAvailable"],
        "host_swap_used_bytes": memory["SwapTotal"] - memory["SwapFree"],
        "host_load_1m": os.getloadavg()[0],
    }


def validate_body(path: str, body: bytes) -> None:
    value = json.loads(body)
    if path == "/api/health":
        if value["status"] != "ready" or value["accepting_runs"] is not True:
            raise ValueError(f"Backend is not ready: {value['status']}")
    elif not isinstance(value, list):
        raise ValueError(f"{path}: expected a resource list")


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    return values[max(0, math.ceil(len(values) * fraction) - 1)] * 1000


def stage(name: str, paths: tuple[str, ...], clients: int, seconds: float,
          interval: float, pid: int) -> dict:
    barrier = threading.Barrier(clients + 1)
    stop = threading.Event()
    deadline = [0.0]
    active = [0, 0]
    lock = threading.Lock()
    samples = [snapshot(pid)]

    def worker(index: int) -> dict:
        connection = http.client.HTTPConnection(HOST, PORT, timeout=3)
        latencies = []
        errors = []
        statuses = Counter()
        route_counts = Counter()
        barrier.wait()
        sequence = index
        while time.monotonic() < deadline[0] and not stop.is_set():
            path = paths[sequence % len(paths)]
            sequence += 1
            started = time.monotonic()
            with lock:
                active[0] += 1
                active[1] = max(active[1], active[0])
            try:
                connection.request("GET", path)
                response = connection.getresponse()
                body = response.read()
                statuses[response.status] += 1
                if response.status != 200:
                    raise ValueError(f"HTTP {response.status}: {body[:200]!r}")
                validate_body(path, body)
                route_counts[path] += 1
            except (OSError, http.client.HTTPException, ValueError, KeyError) as exc:
                errors.append({"path": path, "type": type(exc).__name__, "message": str(exc)})
                stop.set()
            finally:
                latencies.append(time.monotonic() - started)
                with lock:
                    active[0] -= 1
            if interval:
                stop.wait(max(0, interval - (time.monotonic() - started)))
        connection.close()
        return {"latencies": latencies, "errors": errors,
                "statuses": statuses, "route_counts": route_counts}

    start = time.monotonic()
    deadline[0] = start + seconds
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, clients)) as pool:
        futures = [pool.submit(worker, i) for i in range(clients)]
        if clients:
            barrier.wait()
        while time.monotonic() < deadline[0] and not stop.is_set():
            stop.wait(min(1, max(0, deadline[0] - time.monotonic())))
            sample = snapshot(pid)
            samples.append(sample)
            if sample["host_available_bytes"] < 128 * 1024 * 1024:
                stop.set()
        results = [future.result() for future in futures]
    samples.append(snapshot(pid))
    elapsed = time.monotonic() - start
    latencies = sorted(v for result in results for v in result["latencies"])
    errors = [v for result in results for v in result["errors"]]
    successes = len(latencies) - len(errors)
    hz = os.sysconf("SC_CLK_TCK")
    intervals = [
        (b["backend_cpu_ticks"] - a["backend_cpu_ticks"]) / hz
        / (b["monotonic"] - a["monotonic"]) * 100
        for a, b in zip(samples, samples[1:], strict=False)
        if b["monotonic"] - a["monotonic"] >= 0.5
    ]
    return {
        "name": name, "paths": paths, "clients": clients,
        "worker_threads": clients, "max_in_flight_requests": active[1],
        "planned_seconds": seconds, "elapsed_seconds": elapsed,
        "per_client_interval_seconds": interval,
        "requests": len(latencies), "successes": successes, "errors": errors,
        "status_counts": dict(sum((r["statuses"] for r in results), Counter())),
        "successes_by_path": dict(sum((r["route_counts"] for r in results), Counter())),
        "success_rps": successes / elapsed,
        "latency_ms": {"p50": percentile(latencies, 0.5),
                       "p95": percentile(latencies, 0.95),
                       "p99": percentile(latencies, 0.99),
                       "max": max(latencies) * 1000 if latencies else None},
        "backend_cpu_mean_percent_one_core": (
            samples[-1]["backend_cpu_ticks"] - samples[0]["backend_cpu_ticks"]
        ) / hz / elapsed * 100,
        "backend_cpu_peak_sample_percent_one_core": max(intervals, default=0),
        "generator_cpu_mean_percent_one_core": (
            samples[-1]["generator_cpu_ticks"] - samples[0]["generator_cpu_ticks"]
        ) / hz / elapsed * 100,
        "backend_rss_min_bytes": min(s["backend_rss_bytes"] for s in samples),
        "backend_rss_peak_bytes": max(s["backend_rss_bytes"] for s in samples),
        "host_available_min_bytes": min(s["host_available_bytes"] for s in samples),
        "samples": samples, "stopped_early": stop.is_set(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    pid = process_pid()
    result = {
        "started_at_utc": datetime.now(UTC).isoformat(),
        "backend_pid": pid, "base_url": f"http://{HOST}:{PORT}",
        "host": platform.node(), "kernel": platform.release(),
        "host_cpu_count": os.cpu_count(), "generator_python": platform.python_version(),
        "cpu_ticks_per_second": os.sysconf("SC_CLK_TCK"),
        "method": "closed-loop, one dedicated thread/persistent HTTP connection per client",
        "stages": [],
    }
    warm = http.client.HTTPConnection(HOST, PORT, timeout=3)
    for path in ROUTES:
        warm.request("GET", path)
        response = warm.getresponse()
        if response.status != 200:
            raise RuntimeError(f"Preflight {path}: HTTP {response.status}")
        validate_body(path, response.read())
    warm.close()
    plans = [("idle", (), 0, 30, 0), ("light-mixed", ROUTES, 4, 60, 0.5)]
    plans += [("recovery-idle", (), 0, 30, 0)]
    for name, paths, clients, seconds, interval in plans:
        item = stage(name, paths, clients, seconds, interval, pid)
        result["stages"].append(item)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({key: item[key] for key in (
            "name", "clients", "requests", "success_rps", "latency_ms",
            "backend_cpu_mean_percent_one_core", "backend_rss_peak_bytes", "stopped_early",
        )}), flush=True)
        if item["stopped_early"]:
            raise RuntimeError(f"Benchmark stopped; inspect {args.output}")
    result["finished_at_utc"] = datetime.now(UTC).isoformat()
    args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
