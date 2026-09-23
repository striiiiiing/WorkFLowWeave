import asyncio
from contextlib import asynccontextmanager

import pytest
from langchain_core.messages import AIMessage
from pydantic import Field

from logagent.agent.builtin.declaration import ToolDeclaration
from logagent.agent.config import AgentConfig
from logagent.agent.scheduling import ToolScheduler
from logagent.agent.service import AgentService
from logagent.models import AIConfig
from tests.agent.helpers import ScriptedModel


class TurnModel(ScriptedModel):
    tool_sets: list = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        self.tool_sets.append([tool.args_schema.copy() for tool in tools])
        return super().bind_tools(tools, **kwargs)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        if len(self.seen) == 1:
            await asyncio.sleep(0.03)
        return await super()._agenerate(messages, stop, run_manager, **kwargs)


async def test_config_prompt_tools_and_output_limit_are_captured_per_turn(tmp_path):
    seen = []
    leases = []
    initial = AgentConfig(output_tokens=128, summary_max_tokens=128,
                          idle_timeout=1, preview_tokens=1000)
    updated = AgentConfig(output_tokens=256, summary_max_tokens=256,
                          idle_timeout=0.01, preview_tokens=2000)
    schema = {"type": "object", "properties": {}}

    async def invoke(arguments, context):
        seen.append(context.config.preview_tokens)
        if len(seen) == 1:
            service.update_config(updated)
            updated.preview_tokens = 3000
            schema["description"] = "new definition"
            await service.workspace.write("AGENTS.md", "overwrite", "next turn rules")
        return {"status": "success"}

    model = TurnModel(responses=[
        AIMessage(content="", tool_calls=[{"id": "c1", "name": "probe", "args": {}}]),
        AIMessage(content="first"),
        AIMessage(content="", tool_calls=[{"id": "c2", "name": "probe", "args": {}}]),
        AIMessage(content="second"),
    ])

    class AI:
        @asynccontextmanager
        async def lease(self, config, **kwargs):
            leases.append(kwargs["max_output_tokens"])
            yield model

    service = AgentService(
        tmp_path / "workspace", tmp_path / "runtime", config=initial, ai_service=AI(),
        ai_config=AIConfig(id="ai", provider="mock", models={"test": {}}),
        declarations=[ToolDeclaration("probe", "Probe snapshot", schema, "read", invoke)],
    )
    try:
        initial.preview_tokens = 4000
        await service.initialize()
        await service.workspace.write("AGENTS.md", "overwrite", "first turn rules")
        sid = (await service.create_session(model="test"))["session_id"]
        for request_id in ("first", "second"):
            accepted = await service.submit(sid, request_id, request_id=request_id)
            assert (await service.wait(accepted["turn_id"]))["status"] == "completed"
        assert leases == [128, 256]
        assert seen == [1000, 2000]
        prompts = [messages[0].content for messages in model.seen]
        assert prompts[0] == prompts[1]
        assert "first turn rules" in prompts[0]
        assert prompts[2] == prompts[3]
        assert "next turn rules" in prompts[2]
        assert all("description" not in tools[0] for tools in model.tool_sets[:2])
        assert all(tools[0]["description"] == "new definition" for tools in model.tool_sets[2:])
    finally:
        await service.close()


async def test_config_update_and_new_turn_keep_the_workspace_lock(tmp_path):
    service = AgentService(
        tmp_path / "workspace", tmp_path / "runtime",
        model_provider=lambda _: ScriptedModel(responses=[AIMessage(content="done")]),
    )
    entered = asyncio.Event()

    async def reader():
        async with service.scheduler.acquire("read"):
            entered.set()

    try:
        sid = (await service.create_session(model="test"))["session_id"]
        scheduler = service.scheduler
        async with scheduler.acquire("exclusive"):
            service.update_config(AgentConfig(read_concurrency=2))
            turn = await service.submit(sid, "hello", request_id="r1")
            await service.wait(turn["turn_id"])
            assert service.scheduler is scheduler
            assert scheduler.read_concurrency == 2
            task = asyncio.create_task(reader())
            await asyncio.sleep(0.01)
            assert not entered.is_set()
        await task
        assert entered.is_set()
    finally:
        await service.close()


async def test_shrinking_read_capacity_waits_without_stranding_waiters():
    scheduler = ToolScheduler(3)
    release = asyncio.Event()
    entered = asyncio.Queue()

    async def reader(index):
        async with scheduler.acquire("read"):
            entered.put_nowait(index)
            await release.wait()

    readers = [asyncio.create_task(reader(i)) for i in range(3)]
    await asyncio.gather(*(entered.get() for _ in readers))
    resizing = asyncio.create_task(scheduler.resize(1))
    await asyncio.sleep(0)
    assert not resizing.done()
    release.set()
    await asyncio.gather(*readers, resizing)
    assert scheduler.status["read_concurrency"] == 1
    async with scheduler.acquire("read"):
        await scheduler.resize(2)
        async with scheduler.acquire("read"):
            assert scheduler.reading == 2


async def test_cancelled_resize_restores_retired_read_permits():
    scheduler = ToolScheduler(3)
    async with scheduler.acquire("read"), scheduler.acquire("read"):
        resizing = asyncio.create_task(scheduler.resize(1))
        await asyncio.sleep(0)
        resizing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await resizing
        async with asyncio.timeout(1), scheduler.acquire("read"):
            assert scheduler.reading == 3
    assert scheduler.read_concurrency == 3
