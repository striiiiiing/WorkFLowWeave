"""Real Agent persistence, task snapshots and inherited context contracts."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import orjson
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from logagent.agent.service import AgentService
from logagent.ai.errors import ModelError, error_info
from logagent.errors import LogAgentError
from logagent.models import AIConfig
from logagent.workflow.agent_tasks import LEGACY_TASK_MESSAGE, execute_agent_task
from tests.agent.helpers import ScriptedModel


async def complete(service, session_id, *, text="execute", request_id="first"):
    accepted = await service.submit(session_id, text, request_id=request_id)
    return accepted, await service.wait(accepted["turn_id"])


async def test_legacy_prompt_layers_and_original_request_identity_survive_restart(tmp_path):
    model = ScriptedModel(responses=[AIMessage(content="original"), AIMessage(content="followup")])
    paths = tmp_path / "workspace", tmp_path / "runtime"
    config = AIConfig(id="ai", provider="mock", system_prompt="legacy system", models={"model": {}})
    options = dict(operation_id="legacy-operation", workflow_session_id="run", workflow_task_id="task",
                   model="model", ai_config=config, workflow_result="SOURCE",
                   system_prompt="legacy system", input_prompt="legacy input: {input}",
                   user_prompt="", tool_names=[])
    service = AgentService(*paths, model_provider=lambda _: model)
    try:
        session = await service.create_session(**options)
        accepted, original = await complete(
            service, session["session_id"], text=LEGACY_TASK_MESSAGE, request_id="legacy-operation",
        )
        event_path = service.sessions[session["session_id"]].log.path
    finally:
        await service.close()
    events = [orjson.loads(line) for line in event_path.read_bytes().splitlines()]
    created = next(event for event in events if event["type"] == "session.created")
    created.pop("system_prompt")
    created.pop("input_prompt")
    created["user_prompt"] = "legacy input: {input}"
    event_path.write_bytes(b"".join(orjson.dumps(event) + b"\n" for event in events))
    restored = AgentService(*paths, model_provider=lambda _: model)
    try:
        await restored.initialize()
        stored = restored.sessions[session["session_id"]]
        assert (stored.system_prompt, stored.input_prompt, stored.user_prompt) == (
            "legacy system", "legacy input: {input}", "",
        )
        repeated = await execute_agent_task(restored, **options, request_text=LEGACY_TASK_MESSAGE)
        assert repeated.status == "success" and repeated.text == original["text"] == "original"
        assert stored.request_ids["legacy-operation"][0] == accepted["turn_id"]
        assert len(model.seen) == 1
        await complete(restored, session["session_id"], text="followup", request_id="later")
        assert "legacy system" in model.seen[-1][0].content
        assert sum(message.content == "legacy input: SOURCE" for message in model.seen[-1]) == 1
    finally:
        await restored.close()


async def test_title_and_session_source_kinds_survive_restart(tmp_path):
    paths = tmp_path / "workspace", tmp_path / "runtime"
    service = AgentService(*paths)
    try:
        standalone = await service.create_session()
        continued = await service.create_session(workflow_session_id="run")
        subtask = await service.create_session(workflow_session_id="run", workflow_task_id="task")
        changed = await service.set_title(subtask["session_id"], "  告警复盘  ")
        assert changed["title"] == "告警复盘"
        for title in (" ", "a" * 121):
            with pytest.raises(LogAgentError, match="话题名称"):
                await service.set_title(subtask["session_id"], title)
        with pytest.raises(LogAgentError, match="task_id"):
            await service.create_session(workflow_task_id="orphan")
    finally:
        await service.close()
    restored = AgentService(*paths)
    try:
        await restored.initialize()
        expected = ["standalone", "workflow_continue", "workflow_subtask"]
        for session, kind in zip((standalone, continued, subtask), expected, strict=True):
            actual = await restored.get_session(session["session_id"])
            assert actual["session_kind"] == kind
        actual = await restored.get_session(subtask["session_id"])
        assert actual["title"] == "告警复盘"
        assert actual["workflow_task_id"] == "task"
    finally:
        await restored.close()


@pytest.mark.parametrize("tools, expected", [([], []), (["read"], ["read"])])
async def test_each_task_uses_its_own_tool_selection(tmp_path, tools, expected):
    model = ScriptedModel(responses=[AIMessage(content="done")])
    service = AgentService(tmp_path / "workspace", tmp_path / "runtime", model_provider=lambda _: model)
    try:
        session = await service.create_session(
            workflow_session_id="run", workflow_task_id="task", tool_names=tools,
        )
        await complete(service, session["session_id"])
        assert [tool.name for tool in model.bound_tools] == expected
        other = await service.create_session()
        assert len(service._capture_turn_resources(service.sessions[other["session_id"]]).declarations) > 1
    finally:
        await service.close()


async def test_unknown_task_tool_fails_instead_of_enabling_global_tools(tmp_path):
    model = ScriptedModel(responses=[AIMessage(content="must not run")])
    service = AgentService(tmp_path / "workspace", tmp_path / "runtime", model_provider=lambda _: model)
    try:
        session = await service.create_session(
            workflow_session_id="run", workflow_task_id="task", tool_names=["missing"],
        )
        accepted = await service.submit(session["session_id"], "execute", request_id="first")
        with pytest.raises(LogAgentError) as caught:
            await service.wait(accepted["turn_id"])
        assert caught.value.code == "tool_unavailable"
        assert caught.value.details["tools"] == ["missing"]
        assert not model.seen
        events = await service.events(session["session_id"])
        assert events[-1]["type"] == "turn.failed"
        assert events[-1]["error"]["code"] == "tool_unavailable"
    finally:
        await service.close()


@pytest.mark.parametrize("prompt, expected", [
    ("", "raw {input}"),
    ("analyze", "raw {input}\n\nanalyze"),
    ("source: {input}", "source: raw {input}"),
])
async def test_task_input_template_expands_once_and_only_injects_source_once(
    tmp_path, prompt, expected,
):
    model = ScriptedModel(responses=[AIMessage(content="first"), AIMessage(content="second")])
    service = AgentService(tmp_path / "workspace", tmp_path / "runtime", model_provider=lambda _: model)
    try:
        session = await service.create_session(
            workflow_session_id="run", workflow_task_id="task", workflow_result="raw {input}",
            input_prompt=prompt, tool_names=[],
        )
        await complete(service, session["session_id"])
        await complete(service, session["session_id"], text="followup", request_id="second")
        humans = [message.content for message in model.seen[1] if isinstance(message, HumanMessage)]
        assert humans == [expected, "execute", "followup"]
        events = await service.events(session["session_id"])
        assert sum(event["type"] == "workflow.input.used" for event in events) == 1
    finally:
        await service.close()


async def test_workflow_continue_puts_result_and_new_prompt_in_separate_user_messages(tmp_path):
    model = ScriptedModel(responses=[AIMessage(content="done")])
    service = AgentService(tmp_path / "workspace", tmp_path / "runtime",
                           model_provider=lambda _: model)
    try:
        session = await service.create_session(
            workflow_session_id="run", workflow_result={"final": "SOURCE"}, tool_names=[],
        )
        await complete(service, session["session_id"], text="followup")
        humans = [message.content for message in model.seen[0] if isinstance(message, HumanMessage)]
        assert humans == ['{"input": {"final": "SOURCE"}}', "followup"]
    finally:
        await service.close()


@pytest.mark.parametrize("edit_message", [False, True])
async def test_fork_inherits_task_context_without_injecting_workflow_source_again(tmp_path, edit_message):
    model = ScriptedModel(responses=[AIMessage(content="first"), AIMessage(content="second")])
    service = AgentService(tmp_path / "workspace", tmp_path / "runtime", model_provider=lambda _: model)
    try:
        session = await service.create_session(
            workflow_session_id="run", workflow_task_id="task", workflow_result="SOURCE",
            input_prompt="source: {input}", tool_names=[],
        )
        await complete(service, session["session_id"])
        events = await service.events(session["session_id"])
        message = next(event for event in events if event["type"] == "message.user")
        fork = await service.fork(
            session["session_id"], message_id=message["message_id"] if edit_message else None,
        )
        await complete(service, fork["session_id"], text="followup", request_id="second")
        humans = [message.content for message in model.seen[1] if isinstance(message, HumanMessage)]
        assert humans.count("source: SOURCE") == 1
        assert humans[-1] == "followup"
        assert fork["session_kind"] == "workflow_subtask"
        assert fork["workflow_task_id"] == "task"
    finally:
        await service.close()


async def test_task_model_snapshot_survives_resource_edits_restart_and_explicit_model_change(tmp_path):
    model = ScriptedModel(responses=[AIMessage(content="first"), AIMessage(content="second"),
                                     AIMessage(content="changed")])
    leases = []

    class AI:
        @asynccontextmanager
        async def lease(self, config, **options):
            leases.append((config.model_copy(deep=True), options["model"]))
            yield model

    paths = tmp_path / "workspace", tmp_path / "runtime"
    task_config = AIConfig(id="task-ai", provider="mock", base_url="https://task.invalid",
                           system_prompt="task system", models={"task-model": {}})
    live = AIConfig(id="live-ai", provider="mock", models={"live-model": {}})
    resources = SimpleNamespace(invocation_snapshot=lambda: {"ai": {"live-ai": live}})
    service = AgentService(*paths, ai_service=AI(), resources=resources)
    try:
        session = await service.create_session(
            model="task-model", workflow_session_id="run", workflow_task_id="task",
            ai_config=task_config, workflow_result="input", tool_names=[],
        )
        task_config.base_url = "https://changed.invalid"
        await complete(service, session["session_id"])
        assert "task system" in model.seen[0][0].content
        public = str(await service.events(session["session_id"])) + str(session)
        assert "https://task.invalid" not in public
    finally:
        await service.close()
    restored = AgentService(*paths, ai_service=AI(), resources=resources)
    try:
        await restored.initialize()
        await complete(restored, session["session_id"], text="followup", request_id="second")
        assert [(config.id, config.base_url, name) for config, name in leases] == [
            ("task-ai", "https://task.invalid", "task-model"),
            ("task-ai", "https://task.invalid", "task-model"),
        ]
        await restored.set_model(session["session_id"], "live-ai:live-model")
        await complete(restored, session["session_id"], text="changed", request_id="third")
        assert (leases[-1][0].id, leases[-1][1]) == ("live-ai", "live-model")
    finally:
        await restored.close()


async def test_completed_first_turn_can_be_deduplicated_after_restart_and_later_conversation(tmp_path):
    model = ScriptedModel(responses=[AIMessage(content="original"), AIMessage(content="later")])
    paths = tmp_path / "workspace", tmp_path / "runtime"
    options = dict(workflow_session_id="run", workflow_task_id="task", workflow_result="SOURCE",
                   user_prompt="{input}", tool_names=[], operation_id="stable-operation")
    service = AgentService(*paths, model_provider=lambda _: model)
    try:
        session = await service.create_session(**options)
        accepted, original = await complete(service, session["session_id"], request_id="stable-operation")
        await complete(service, session["session_id"], text="later", request_id="later")
    finally:
        await service.close()
    restored = AgentService(*paths, model_provider=lambda _: model)
    try:
        await restored.initialize()
        replay = await restored.create_session(**options)
        assert replay["session_id"] == session["session_id"]
        repeated = await restored.submit(replay["session_id"], "execute", request_id="stable-operation")
        assert repeated["deduplicated"]
        assert repeated["turn_id"] == accepted["turn_id"]
        result = await restored.wait(repeated["turn_id"])
        assert result["status"] == "completed"
        assert result["text"] == original["text"] == "original"
        assert len(model.seen) == 2
    finally:
        await restored.close()


async def test_failed_provider_diagnostic_survives_restart(tmp_path):
    error = ModelError("provider_unavailable", "上游失败", status_code=502,
                       response_body='{"error":"stream interrupted"}')
    error.report = error_info(error)

    class FailingModel(ScriptedModel):
        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            raise error

    model = FailingModel(responses=[])
    paths = tmp_path / "workspace", tmp_path / "runtime"
    service = AgentService(*paths, model_provider=lambda _: model)
    try:
        session = await service.create_session(model="test", tool_names=[])
        accepted = await service.submit(session["session_id"], "execute", request_id="first")
        with pytest.raises(ModelError):
            await service.wait(accepted["turn_id"])
    finally:
        await service.close()
    restored = AgentService(*paths, model_provider=lambda _: model)
    try:
        await restored.initialize()
        result = await restored.wait(accepted["turn_id"])
        assert result["status"] == "failed"
        assert result["error"] == error.report.model_dump(mode="json")
    finally:
        await restored.close()
