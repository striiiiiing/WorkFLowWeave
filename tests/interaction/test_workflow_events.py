"""真实 HTTP/SSE：就绪后查询、逐项更新、断开及恢复参数。"""

import asyncio
import json
import socket
from types import SimpleNamespace

import httpx
import uvicorn
from fastapi import FastAPI

from logagent.interaction.dependencies import get_services
from logagent.interaction.routers import router
from tests.workflow.helpers import AI, snapshot
from tests.workflow.test_workflow_recovery import close, service


async def event(lines):
    kind = None
    async with asyncio.timeout(5):
        async for line in lines:
            if line.startswith("event: "):
                kind = line[7:]
            elif line.startswith("data: "):
                return kind, json.loads(line[6:])
    raise AssertionError("SSE ended before event")


async def test_real_sse_ready_query_progress_and_reconnect_do_not_execute_again(tmp_path):
    ai = AI(block="second")
    w, store, collector, _, channel = service(tmp_path / "runs.sqlite3", ai=ai)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_services] = lambda: SimpleNamespace(workflow=w, session_view=w.session_view)
    ready = asyncio.Event()

    class Server(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            ready.set()

    server = Server(uvicorn.Config(app, log_level="error", lifespan="off", access_log=False))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    serving = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(5):
            await ready.wait()
        await w.trigger(snapshot(channels=False), session_id="run")
        await ai.started.wait()
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=5) as client:
            async with client.stream("GET", "/api/sessions/run/events") as response:
                assert response.status_code == 200
                lines = response.aiter_lines()
                assert await event(lines) == ("ready", {"session_id": "run"})
                record = (await client.get("/api/sessions/run")).json()
                assert record["execution_epoch"]
                assert next(p for p in record["progress"] if p["item_id"] == "first")["status"] == "success"
            # EOF/disconnect only releases the observer; the blocked run survives.
            assert w.coordinator.contains("run")
            calls = len(collector.calls), len(ai.calls), len(channel.calls)
            async with client.stream("GET", "/api/sessions/run/events") as response:
                lines = response.aiter_lines()
                assert (await event(lines))[0] == "ready"
                assert calls == (len(collector.calls), len(ai.calls), len(channel.calls))
                cancelled = await client.post("/api/sessions/run/cancel")
                assert cancelled.json()["cancelled"] is True
                kind, final = await event(lines)
                assert kind == "progress" and final["status"] == "cancelled"
                assert (await w.wait("run")).status == "cancelled"
            ai.block = None
            result = await client.post("/api/sessions/run/resume", json={
                "stage": "analyze", "request_id": "http-resume",
            })
            assert result.status_code == 202
            await w.wait("run")
            final = (await client.get("/api/sessions/run")).json()
            assert final["status"] == "completed" and final["execution_epoch"] != record["execution_epoch"]
            calls = len(ai.calls)
            assert (await client.post("/api/sessions/run/resume", json={
                "stage": "analyze", "request_id": "http-resume",
            })).status_code == 202
            assert len(ai.calls) == calls
            availability = (await client.get("/api/sessions/run/recovery", params={"stage": "notify"})).json()
            assert availability["available"]
    finally:
        server.should_exit = True
        await serving
        sock.close()
        await close(w, store)
