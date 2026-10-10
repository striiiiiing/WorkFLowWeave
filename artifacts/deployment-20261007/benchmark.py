"""Serial native/container benchmark; run as root on the dedicated test host."""

import argparse
import concurrent.futures
import json
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path("/opt/logagent")
STATE = Path("/opt/logagent-native")
OUT = Path("/opt/logagent-benchmark")
CGROUP = Path("/sys/fs/cgroup")
SECONDS = 60


def command(args):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        print(result.stderr, file=sys.stderr, flush=True)
        result.check_returncode()
    return result.stdout


def api(port, path, body=None):
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read()


def groups(mode):
    if mode.startswith("native"):
        names = ["wwbench-backend"]
        if mode.endswith("full"):
            names.append("wwbench-frontend")
        return [
            CGROUP
            / command(["systemctl", "show", name, "-p", "ControlGroup", "--value"])
            .strip()
            .lstrip("/")
            for name in names
        ]
    ids = command(["docker", "compose", *compose_files(mode), "ps", "-q"]).split()
    paths = []
    for container in ids:
        pid = command(["docker", "inspect", "-f", "{{.State.Pid}}", container]).strip()
        line = Path(f"/proc/{pid}/cgroup").read_text().splitlines()[0]
        paths.append(CGROUP / line.split(":", 2)[2].lstrip("/"))
    return paths


def compose_files(mode):
    return (
        ["-f", "compose.yaml", "-f", "compose.backend.yaml"]
        if mode == "docker-backend"
        else ["-f", "compose.yaml"]
    )


def sample(paths):
    rss = cpu = working = memory = 0
    pids = set()
    for path in paths:
        cpu += int(
            dict(line.split() for line in (path / "cpu.stat").read_text().splitlines())[
                "usage_usec"
            ]
        )
        current = int((path / "memory.current").read_text())
        stats = dict(line.split() for line in (path / "memory.stat").read_text().splitlines())
        memory += current
        working += max(0, current - int(stats.get("inactive_file", 0)))
        for procfile in path.rglob("cgroup.procs"):
            pids.update(procfile.read_text().split())
    for pid in pids:
        try:
            status = Path(f"/proc/{pid}/status").read_text().splitlines()
        except FileNotFoundError:
            continue
        rss += sum(int(line.split()[1]) * 1024 for line in status if line.startswith("VmRSS:"))
    meminfo = dict(
        (line.split(":")[0], int(line.split()[1]) * 1024)
        for line in Path("/proc/meminfo").read_text().splitlines()
    )
    return {
        "monotonic": time.monotonic(),
        "cpu_usec": cpu,
        "rss_bytes": rss,
        "cgroup_memory_bytes": memory,
        "working_set_bytes": working,
        "host_available_bytes": meminfo["MemAvailable"],
        "host_total_bytes": meminfo["MemTotal"],
    }


def stop(mode):
    if mode.startswith("native"):
        for name in ["wwbench-frontend", "wwbench-backend"]:
            result = subprocess.run(
                ["systemctl", "is-active", name], capture_output=True, text=True
            )
            if result.stdout.strip() == "active":
                command(["systemctl", "stop", name])
        return
    command(["docker", "compose", *compose_files(mode), "down"])


def ready(port):
    try:
        return json.loads(api(port, "/api/health"))["status"] == "ready"
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return False


def start(mode):
    before = time.monotonic()
    if mode.startswith("native"):
        command(
            [
                "systemd-run",
                "--unit=wwbench-backend",
                "--collect",
                "--property=WorkingDirectory=/opt/logagent-native",
                "--property=MemoryAccounting=yes",
                "--property=CPUAccounting=yes",
                "--setenv=PATH=/opt/logagent/.venv/bin:/usr/local/bin:/usr/bin:/bin",
                str(ROOT / ".venv/bin/workflowweave"),
                "start",
                "--config",
                str(STATE / "config.json"),
            ]
        )
        if mode.endswith("full"):
            command(
                [
                    "systemd-run",
                    "--unit=wwbench-frontend",
                    "--collect",
                    "--property=MemoryAccounting=yes",
                    "--property=CPUAccounting=yes",
                    "/usr/sbin/nginx",
                    "-g",
                    "daemon off;",
                    "-c",
                    str(STATE / "nginx.conf"),
                    "-p",
                    str(STATE),
                ]
            )
    else:
        args = ["docker", "compose", *compose_files(mode), "up", "-d", "--no-build"]
        if mode.endswith("backend"):
            args.append("backend")
        command(args)
    port = 3000 if mode.endswith("full") else 4300
    deadline = before + 180
    while not ready(port):
        if time.monotonic() > deadline:
            raise TimeoutError(f"{mode} failed to become ready within 180 seconds")
        time.sleep(0.25)
    duration = time.monotonic() - before
    health = json.loads(api(port, "/api/health"))
    (OUT / f"{mode}-health.json").write_text(json.dumps(health, indent=2))
    if mode.endswith("full"):
        assert b"<html" in api(port, "/").lower()
        assert b"openapi" in api(port, "/openapi.json")
        assert b"<html" in api(port, "/resources").lower()
    return duration, port


def measure(mode, phase, paths, load=None):
    samples = [sample(paths)]
    end = time.monotonic() + SECONDS
    while time.monotonic() < end:
        time.sleep(1)
        samples.append(sample(paths))
    if load:
        load.set()
    cpus = [
        (b["cpu_usec"] - a["cpu_usec"]) / ((b["monotonic"] - a["monotonic"]) * 10000)
        for a, b in zip(samples, samples[1:], strict=False)
    ]
    (OUT / f"{mode}-{phase}.jsonl").write_text("".join(json.dumps(s) + "\n" for s in samples))
    return {
        "duration_seconds": samples[-1]["monotonic"] - samples[0]["monotonic"],
        "cpu_mean_one_core_percent": statistics.mean(cpus),
        "cpu_peak_one_core_percent": max(cpus),
        "rss_mean_mib": statistics.mean(s["rss_bytes"] for s in samples) / 2**20,
        "rss_peak_mib": max(s["rss_bytes"] for s in samples) / 2**20,
        "working_set_mean_mib": statistics.mean(s["working_set_bytes"] for s in samples) / 2**20,
        "working_set_peak_mib": max(s["working_set_bytes"] for s in samples) / 2**20,
        "host_available_min_mib": min(s["host_available_bytes"] for s in samples) / 2**20,
    }


def client(port, done):
    latency = []
    failures = []
    while not done.is_set():
        for path, body in [("/api/health", None), ("/api/sources/benchmark_uname/collect", {})]:
            before = time.monotonic()
            try:
                value = json.loads(api(port, path, body))
                if value["status"] not in ("ready", "success"):
                    raise ValueError(value)
                latency.append((time.monotonic() - before) * 1000)
            except Exception as error:
                failures.append(repr(error))
                done.set()
                return latency, failures
            if done.is_set():
                break
        time.sleep(0.1)
    return latency, failures


def disk():
    paths = [
        ROOT / ".venv",
        ROOT / "src",
        ROOT / "plugins",
        ROOT / "frontend/dist",
        Path("/opt/node"),
        Path("/opt/workflowweave-python"),
        Path("/usr/local/bin/node"),
        Path("/root/.local/share/uv/python"),
        Path("/usr/local/bin/uv"),
        Path("/usr/local/bin/uvx"),
        STATE,
        Path("/var/lib/docker"),
        Path("/var/lib/containerd"),
    ]
    sizes = {
        str(p): int(command(["du", "-sx", "-B1", str(p)]).split()[0]) for p in paths if p.exists()
    }
    (OUT / "docker-system-df.txt").write_text(command(["docker", "system", "df", "-v"]))
    (OUT / "filesystem.txt").write_text(command(["df", "-B1", "/"]))
    volumes = json.loads(command(["docker", "volume", "inspect", "workflowweave_state"]))
    volume = volumes[0]["Mountpoint"]
    sizes["docker_state"] = int(command(["du", "-s", "-B1", volume]).split()[0])
    sizes["images"] = json.loads(
        command(
            [
                "docker",
                "image",
                "inspect",
                "ghcr.io/striiiiiing/workflowweave-backend:latest",
                "ghcr.io/striiiiiing/workflowweave-frontend:latest",
            ]
        )
    )
    return sizes


def main():
    mode = argparse.ArgumentParser()
    mode.add_argument(
        "mode", choices=["native-backend", "native-full", "docker-backend", "docker-full"]
    )
    selected = mode.parse_args().mode
    OUT.mkdir(exist_ok=True)
    result = {
        "mode": selected,
        "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "startup_seconds": [],
    }
    result["runtime_versions"] = {
        "python": command([str(ROOT / ".venv/bin/python"), "--version"]).strip()
        if selected.startswith("native")
        else "Python 3.12.15 (published image)",
        "docker": command(["docker", "--version"]).strip(),
        "kernel": command(["uname", "-r"]).strip(),
        "swap": command(["free", "-b"]).strip(),
    }
    for _ in range(3):
        stop(selected)
        time.sleep(1)
        duration, port = start(selected)
        result["startup_seconds"].append(duration)
        (OUT / f"{selected}-startup.json").write_text(json.dumps(result, indent=2))
    source = {
        "id": "benchmark_uname",
        "call": {"kind": "cli", "mode": "argv", "executable": "uname", "argv": ["-a"]},
    }
    existing = json.loads(api(port, "/api/sources"))
    if not any(s["id"] == source["id"] for s in existing):
        api(port, "/api/sources", source)
    collection = json.loads(api(port, "/api/sources/benchmark_uname/collect", {}))
    assert collection["status"] == "success", collection
    (OUT / f"{selected}-collection.json").write_text(json.dumps(collection, indent=2))
    paths = groups(selected)
    time.sleep(10)
    result["idle"] = measure(selected, "idle", paths)
    done = threading.Event()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(client, port, done) for _ in range(4)]
        result["load"] = measure(selected, "load", paths, done)
        outcomes = [f.result() for f in futures]
    latency = sorted(t for times, _ in outcomes for t in times)
    result["load"].update(
        {
            "successful_requests": len(latency),
            "failures": [e for _, errors in outcomes for e in errors],
            "latency_p50_ms": statistics.median(latency) if latency else None,
            "latency_p95_ms": latency[min(len(latency) - 1, int(len(latency) * 0.95))]
            if latency
            else None,
        }
    )
    result["disk"] = disk()
    result["infrastructure_processes"] = command(
        ["ps", "-C", "dockerd,containerd,containerd-shim-runc-v2", "-o", "pid,rss,comm"]
    ).strip()
    (OUT / f"{selected}.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "disk"}, indent=2), flush=True)
    assert not result["load"]["failures"], result["load"]["failures"]
    stop(selected)


if __name__ == "__main__":
    main()
