"""Business pressure test: real backend/SQLite/CLI/MCP/file notifications.

Only the model provider is synthetic: a local OpenAI HTTP/SSE fixture. Linux
cgroup v2 limits apply to the backend and all its CLI/MCP subprocesses; the
generator and model fixture run outside that cgroup. No production state is used.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
BACKEND_PORT = 4399
MODEL_PORT = 9919
MIB = 1024 * 1024
TEXT = "BENCHMARK_RESPONSE " + "facts risks evidence conclusion " * 32
UNIT = "workflowweave-business-pressure"


def records(count):
    return [{"id": i, "time": "2026-10-08T00:00:00Z", "source": "fixture",
             "title": f"Business observation {i}", "body": "fact and evidence " * 12,
             "value": i * 0.1} for i in range(count)]


def fixture_mcp():
    from mcp.server.fastmcp import FastMCP
    server = FastMCP("business-pressure-fixture")

    @server.tool()
    def business_records(count: int = 100) -> list[dict]:
        """Return deterministic news/log records for a backend capacity experiment."""
        if not 1 <= count <= 1000:
            raise ValueError("count must be between 1 and 1000")
        return records(count)

    server.run(transport="stdio")


class ModelHandler(BaseHTTPRequestHandler):
    ledger = []
    protocol_version = "HTTP/1.1"

    def do_POST(self):  # noqa: N802
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        body = json.loads(raw)
        if self.path != "/v1/chat/completions" or body.get("stream") is not True:
            self.send_error(400, "fixture requires streaming chat completions")
            return
        type(self).ledger.append({"at": time.monotonic(), "request_bytes": len(raw),
                                  "sha256": hashlib.sha256(raw).hexdigest()})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            for index in range(20):
                time.sleep(.05)
                chunk = {"id": "fixture", "object": "chat.completion.chunk",
                         "created": 1791417600, "model": "gpt-4o-mini",
                         "choices": [{"index": 0, "delta": {"content": TEXT[index::20]},
                                      "finish_reason": None}]}
                # Contiguous fragments preserve exact expected output.
                start, end = len(TEXT) * index // 20, len(TEXT) * (index + 1) // 20
                chunk["choices"][0]["delta"]["content"] = TEXT[start:end]
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                self.wfile.flush()
            chunk["choices"] = [{"index": 0, "delta": {}, "finish_reason": "stop"}]
            self.wfile.write(("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode())
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            # Cancellation is a recorded external event, never reported as success.
            type(self).ledger.append({"at": time.monotonic(), "disconnected": True})

    def log_message(self, *_args):
        pass


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def cg_values(path):
    return {key: int(value) for key, value in
            (line.split() for line in path.read_text().splitlines())}


def sample(cgroup):
    memory = cg_values(cgroup / "memory.stat")
    return {"monotonic": time.monotonic(),
            "cpu": cg_values(cgroup / "cpu.stat"),
            "memory_current_bytes": int((cgroup / "memory.current").read_text()),
            "working_set_bytes": max(0, int((cgroup / "memory.current").read_text())
                                      - memory["inactive_file"]),
            "swap_bytes": int((cgroup / "memory.swap.current").read_text()),
            "memory_events": cg_values(cgroup / "memory.events")}


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[math.ceil(len(ordered) * fraction) - 1] * 1000


class Measurement:
    def __init__(self, client, cgroup):
        self.client, self.cgroup = client, cgroup
        self.requests, self.runs, self.sampling_errors = [], [], []
        self.samples = [sample(cgroup)]

    async def api(self, method, path, body=None, expected=200):
        started = time.monotonic()
        response = await self.client.request(method, path, json=body)
        self.requests.append({"method": method, "path": path,
                              "elapsed_seconds": time.monotonic() - started,
                              "status": response.status_code, "bytes": len(response.content)})
        if response.status_code != expected:
            raise RuntimeError(f"{method} {path}: {response.status_code}: {response.text[:1000]}")
        return response.json()

    async def workflow(self, name):
        started = time.monotonic()
        accepted = await self.api("POST", f"/api/workflows/{name}/run", expected=202)
        sid = accepted["session_id"]
        snapshots = []
        async with self.client.stream("GET", f"/api/sessions/{sid}/events") as response:
            if response.status_code != 200:
                raise RuntimeError(f"SSE failed: {response.status_code}")
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    snapshots.append(json.loads(line[6:]))
        if not snapshots or snapshots[-1]["status"] != "completed":
            raise RuntimeError(f"Workflow {sid} did not complete: {snapshots[-1:]}")
        final = await self.api("GET", f"/api/sessions/{sid}")
        phases = {}
        for stage in ("collect", "analyze", "aggregate", "notify"):
            phases[stage] = await self.api(
                "GET", f"/api/sessions/{sid}/phases/{stage}?version={final['version']}")
            if phases[stage]["availability"] != "available":
                raise RuntimeError(f"{sid}: {stage} archive unavailable")
        collected = phases["collect"]["content"]["collection"]
        if any(item["status"] != "success" for item in collected):
            raise RuntimeError(f"{sid}: collection failed: {collected}")
        # Final output and delivery assertions detect empty or partial success.
        if TEXT not in json.dumps(phases["aggregate"]["content"]):
            raise RuntimeError(f"{sid}: model output missing from archive")
        deliveries = phases["notify"]["content"]["deliveries"]
        if not deliveries or any(item["status"] != "success" for item in deliveries):
            raise RuntimeError(f"{sid}: file notification failed: {deliveries}")
        self.runs.append({"workflow": name, "session_id": sid,
                          "elapsed_seconds": time.monotonic() - started,
                          "status": final["status"], "version": final["version"],
                          "sse_frames": len(snapshots), "deliveries": len(deliveries)})

    async def browse(self, seconds, rate):
        paths = ("/api/workflows", "/api/sources", "/api/sessions?limit=20", "/api/health")
        start = time.monotonic()
        for index in range(int(seconds * rate)):
            await asyncio.sleep(max(0, start + index / rate - time.monotonic()))
            value = await self.api("GET", paths[index % len(paths)])
            if paths[index % len(paths)] == "/api/health" and value["status"] != "ready":
                raise RuntimeError(f"backend unhealthy: {value}")

    async def timed(self, name, operation):
        start = time.monotonic()
        stop = asyncio.Event()

        async def sampling():
            while not stop.is_set():
                await asyncio.sleep(.25)
                try:
                    self.samples.append(sample(self.cgroup))
                except FileNotFoundError as exc:
                    self.sampling_errors.append(f"cgroup disappeared: {exc}")
                    return

        sampler = asyncio.create_task(sampling())
        try:
            await operation
        finally:
            stop.set()
            await sampler
        if self.sampling_errors:
            raise RuntimeError(self.sampling_errors)
        self.samples.append(sample(self.cgroup))
        duration = time.monotonic() - start
        latencies = [item["elapsed_seconds"] for item in self.requests]
        run_latencies = [item["elapsed_seconds"] for item in self.runs]
        return {"name": name, "elapsed_seconds": duration,
                "api_requests": len(latencies), "api_status_counts": dict(Counter(
                    item["status"] for item in self.requests)),
                "api_latency_ms": {"p50": percentile(latencies, .5), "p95": percentile(latencies, .95),
                                   "p99": percentile(latencies, .99)},
                "workflow_runs": len(self.runs), "completed_runs": len(self.runs),
                "workflow_latency_ms": {"p50": percentile(run_latencies, .5),
                                        "p95": percentile(run_latencies, .95)},
                "cpu_mean_percent_one_core": (self.samples[-1]["cpu"]["usage_usec"]
                    - self.samples[0]["cpu"]["usage_usec"]) / 1e6 / duration * 100,
                "cpu_throttled_seconds": (self.samples[-1]["cpu"]["throttled_usec"]
                    - self.samples[0]["cpu"]["throttled_usec"]) / 1e6,
                "memory_peak_bytes": max(s["memory_current_bytes"] for s in self.samples),
                "working_set_peak_bytes": max(s["working_set_bytes"] for s in self.samples),
                "swap_peak_bytes": max(s["swap_bytes"] for s in self.samples),
                "samples": self.samples, "requests": self.requests, "runs": self.runs}


async def batches(measurement, batches_count, interval, names):
    start = time.monotonic()
    for index in range(batches_count):
        await asyncio.sleep(max(0, start + index * interval - time.monotonic()))
        await asyncio.gather(*(measurement.workflow(name) for name in names))
        # A business terminal event precedes deferred checkpoint reconciliation.
        # This explicit inter-batch quiet period is part of the workload, not a
        # hidden retry. Capacity errors still fail the experiment immediately.
        await asyncio.sleep(5)


async def stage_operations(measurement, seconds, rate, count, names):
    # TaskGroup cancels other generators on an error before server shutdown.
    async with asyncio.TaskGroup() as group:
        group.create_task(measurement.browse(seconds, rate))
        group.create_task(batches(measurement, count, seconds / count if count else 0, names))
        group.create_task(asyncio.sleep(seconds))


async def setup(client, directory):
    async def create(kind, body):
        response = await client.post(f"/api/{kind}", json=body)
        if response.status_code != 201:
            raise RuntimeError(f"create {kind}: {response.status_code}: {response.text}")

    await create("mcp_servers", {"id": "fixture", "transport": "stdio", "command": sys.executable,
                                  "args": [str(SCRIPT), "--fixture-mcp"]})
    input_file = directory / "records.json"
    input_file.write_text(json.dumps(records(100)), encoding="utf-8")
    await create("sources", {"id": "cli-records", "call": {"kind": "cli", "mode": "argv",
                                                          "executable": "cat", "argv": [str(input_file)]}})
    for count in (100, 1000):
        await create("sources", {"id": f"mcp-{count}", "call": {"kind": "mcp", "server": "fixture",
                                "tool": "business_records", "arguments": {"count": count}}})
    await create("ai", {"id": "fixture", "provider": "openai_compatible_api",
                        "base_url": f"http://127.0.0.1:{MODEL_PORT}/v1", "retries": 0,
                        "models": {"gpt-4o-mini": {"streaming": True}}})
    await create("channels", {"id": "archive", "channel": "file",
                              "options": {"path": str(directory / "notifications.log")}})
    for name, task_count, fan_in, source in (("news", 1, True, "mcp-100"),
            ("stock", 3, True, "mcp-100"), ("issues", 2, False, "cli-records"),
            ("large", 3, True, "mcp-1000")):
        body = {"id": name, "name": f"benchmark-{name}", "sources": [source],
                "analyses": [{"id": f"task-{i}", "ai": "fixture", "model": "gpt-4o-mini",
                              "user_prompt": "Analyze the provided business observations."}
                             for i in range(task_count)], "channels": ["archive"],
                "analysis_concurrency": 3, "input_processing": {"format": "none"}}
        if fan_in:
            body["fan_in"] = {"reuse_from": "$first", "user_prompt": "Summarize the analyses."}
        await create("workflows", body)
    return len(input_file.read_bytes()), len(json.dumps(records(1000)).encode())


async def main(args):
    model = ThreadingHTTPServer(("127.0.0.1", MODEL_PORT), ModelHandler)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    result = {"started_at_utc": datetime.now(UTC).isoformat(), "stages": [],
              "environment": {"os": platform.platform(), "python": platform.python_version(),
                              "host_cpu_count": os.cpu_count(), "cpu_model": command("lscpu"),
                              "git_head": command("git", "rev-parse", "HEAD")},
              "model_fixture": {"chunks": 20, "chunk_interval_seconds": .05,
                                "response_bytes": len(TEXT.encode()), "real_inference": False},
              "limits": {"cpu_quota": "100000 100000", "memory_max": 512 * MIB, "swap_max": 0}}
    args.output.mkdir(parents=True, exist_ok=True)

    def persist():
        (args.output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")

    with tempfile.TemporaryDirectory(prefix="workflowweave-business-pressure-") as temporary:
        directory = Path(temporary)
        log_path = args.output.resolve() / "backend.log"
        log_path.write_text("")
        config = directory / "config.json"
        config.write_text(json.dumps({"data_dir": str(directory / "data"), "plugin_dir": str(ROOT / "plugins"),
                                     "port": BACKEND_PORT, "master_key_file": str(directory / "master.key")}))
        command("systemd-run", "--user", f"--unit={UNIT}", "--quiet",
                "-p", "CPUQuota=100%", "-p", "MemoryMax=512M", "-p", "MemorySwapMax=0",
                "-p", f"WorkingDirectory={ROOT}", "-p", f"StandardOutput=append:{log_path}",
                "-p", f"StandardError=append:{log_path}", "--setenv=PYTHONPATH=" + str(ROOT / "src"),
                sys.executable, "-m", "workflowweave.interaction.cli", "start", "--config", str(config))
        try:
            cgroup = Path("/sys/fs/cgroup") / command("systemctl", "--user", "show", UNIT,
                                                    "-p", "ControlGroup", "--value").lstrip("/")
            actual_limits = {file: (cgroup / file).read_text().strip()
                             for file in ("cpu.max", "memory.max", "memory.swap.max")}
            result["actual_limits"] = actual_limits
            if actual_limits != {"cpu.max": "100000 100000", "memory.max": str(512 * MIB), "memory.swap.max": "0"}:
                raise RuntimeError(f"resource limits did not apply: {actual_limits}")
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{BACKEND_PORT}",
                                         timeout=30, limits=httpx.Limits(max_connections=40)) as client:
                startup_started = time.monotonic()
                for _attempt in range(90):
                    try:
                        response = await client.get("/api/health")
                        if response.status_code == 200 and response.json()["status"] == "ready":
                            break
                    except httpx.ConnectError:
                        pass  # Only the explicit startup window tolerates no listener.
                    await asyncio.sleep(1)
                else:
                    raise RuntimeError("backend startup timed out; inspect backend.log")
                result["startup_seconds"] = time.monotonic() - startup_started
                result["input_bytes"] = dict(zip(("100_records", "1000_records"),
                                                  await setup(client, directory), strict=True))
                preflight = Measurement(client, cgroup)
                await preflight.workflow("stock")
                result["preflight"] = preflight.runs
                plans = (("idle", 15, 0, 0, []),
                         ("daily", 60, 2, 4, ["news"]),
                         ("burst", 60, 8, 4, ["news", "stock", "issues", "stock"]),
                         ("soak", args.soak_seconds, 2, args.soak_seconds // 15,
                          ["news", "stock", "issues"]),
                         ("recovery-idle", 30, 0, 0, []),
                         ("large-input", 20, 2, 1, ["large"] * 4))
                for name, seconds, rate, count, names in plans:
                    if name not in args.stages.split(","):
                        continue
                    measurement = Measurement(client, cgroup)
                    before = len(ModelHandler.ledger)
                    operation = stage_operations(measurement, seconds, rate, count, names)
                    try:
                        stage = await measurement.timed(name, operation)
                    except BaseException:
                        result["incomplete_stage"] = {"name": name, "samples": measurement.samples,
                                                     "requests": measurement.requests,
                                                     "runs": measurement.runs,
                                                     "sampling_errors": measurement.sampling_errors}
                        raise
                    stage["model_ledger"] = ModelHandler.ledger[before:]
                    result["stages"].append(stage)
                    persist()
                    print(json.dumps({k: stage[k] for k in ("name", "workflow_runs", "api_requests",
                        "api_latency_ms", "workflow_latency_ms", "cpu_mean_percent_one_core",
                        "memory_peak_bytes", "working_set_peak_bytes", "swap_peak_bytes")}), flush=True)
                result["final_health"] = (await client.get("/api/health")).json()
                result["final_memory_events"] = cg_values(cgroup / "memory.events")
                result["cgroup_lifetime_peak_bytes"] = int((cgroup / "memory.peak").read_text())
                result["notification_count"] = (directory / "notifications.log").read_text().count("Z channel=")
                result["database_files"] = {p.name: p.stat().st_size for p in (directory / "data").glob("workflows.sqlite3*")}
                result["completion_status"] = "completed"
                result["finished_at_utc"] = datetime.now(UTC).isoformat()
                persist()
        except BaseException as exc:
            result["completion_status"] = "failed"
            result["error"] = f"{type(exc).__name__}: {exc}"
            result["systemd_result"] = command("systemctl", "--user", "show", UNIT,
                                               "-p", "Result", "-p", "ExecMainStatus")
            persist()
            raise
        finally:
            command("systemctl", "--user", "stop", UNIT)
            model.shutdown()
            model.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-mcp", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("artifacts/backend-business-pressure-20261008"))
    parser.add_argument("--soak-seconds", type=int, default=180)
    parser.add_argument("--stages", default="idle,daily,burst,soak,recovery-idle",
                        help="Comma-separated stages; large-input intentionally tests the OOM boundary")
    arguments = parser.parse_args()
    if arguments.fixture_mcp:
        fixture_mcp()
    else:
        if arguments.soak_seconds < 15 or arguments.soak_seconds % 15:
            parser.error("--soak-seconds must be a positive multiple of 15")
        asyncio.run(main(arguments))
