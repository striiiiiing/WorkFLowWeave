"""Slash command targets must not be inferred from the current routing session."""

import pytest

from tests.agent.helpers import ScriptedModel
from workflowweave.agent.commands import AgentCommand, CommandDispatcher, parse_command
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.interaction.fastapi.agent import create_agent_service


@pytest.fixture
async def service(tmp_path):
    agent = create_agent_service(
        tmp_path / "workspace", tmp_path / "runtime",
        model_provider=lambda _: ScriptedModel(responses=[]),
    )
    await agent.initialize()
    try:
        yield agent
    finally:
        await agent.close()


def test_command_parser_preserves_message_and_append_content_spacing():
    message = "  普通消息\n  保留正文缩进  "
    assert parse_command(message) == ("message", message)
    assert parse_command("/append   保留正文缩进") == ("append", "  保留正文缩进")
    with pytest.raises(WorkFLowWeaveError) as unknown:
        parse_command("/unknown argument")
    assert unknown.value.code == "invalid_argument"


@pytest.mark.parametrize("bound", [False, True])
async def test_resume_without_argument_lists_history_even_with_a_bound_session(service, bound):
    commands = CommandDispatcher(service)
    empty = await commands.dispatch(AgentCommand(text="/resume"))
    assert empty["kind"] == "sessions"
    assert empty["result"] == []

    first = await service.create_session()
    second = await service.create_session()
    await service.set_title(first["session_id"], "生产告警复盘")
    before = {sid: await service.events(sid) for sid in service.sessions}

    listed = await commands.dispatch(AgentCommand(
        session=first["session_id"] if bound else None, text=" /resume \t ",
    ))
    assert listed["kind"] == "sessions"
    assert listed["priority"] == "command"
    assert listed["result"] == await service.list_sessions()
    assert {item["session_id"] for item in listed["result"]} == {
        first["session_id"], second["session_id"],
    }
    assert {sid: await service.events(sid) for sid in service.sessions} == before


@pytest.mark.parametrize("separator", [" ", "    ", "\t", "\n"])
async def test_resume_with_explicit_id_reads_that_session(service, separator):
    current = await service.create_session()
    target = await service.create_session()
    result = await CommandDispatcher(service).dispatch(AgentCommand(
        session=current["session_id"], text=f"/resume{separator}{target['session_id']}  ",
    ))
    assert result["kind"] == "session"
    assert result["result"] == target


async def test_explicit_resume_action_keeps_session_target_contract(service):
    commands = CommandDispatcher(service)
    assert (await commands.dispatch(AgentCommand(action="resume")))["result"] == []
    target = await service.create_session()
    resumed = await commands.dispatch(AgentCommand(action="resume", session=target["session_id"]))
    assert resumed["kind"] == "session"
    assert resumed["result"] == target
    with pytest.raises(WorkFLowWeaveError) as missing:
        await commands.dispatch(AgentCommand(text="/resume missing-session"))
    assert missing.value.code == "session_not_found"


@pytest.mark.parametrize(
    ("text", "usage"),
    [
        ("/new extra", "/new"),
        ("/stop extra", "/stop"),
        ("/compact extra", "/compact"),
        ("/append", "/append"),
        ("/resume one two", "/resume <session_id>"),
        ("/workflow one two", "/workflow <session_id>"),
        ("/fork one two", "/fork [turn_id]"),
    ],
)
async def test_invalid_command_arguments_are_rejected_before_execution(service, text, usage):
    with pytest.raises(WorkFLowWeaveError) as error:
        await CommandDispatcher(service).dispatch(AgentCommand(text=text))
    assert error.value.code == "invalid_argument"
    assert usage in str(error.value)


def test_id_command_arguments_are_trimmed_without_changing_append_body():
    assert AgentCommand(text="/workflow    run_1\t").operation() == ("workflow", "run_1")
    assert AgentCommand(text="/fork\nturn_1  ").operation() == ("fork", "turn_1")
    assert AgentCommand(text="/append    保留前导空格").operation() == ("append", "   保留前导空格")


async def test_resume_lists_persisted_history_after_restart(tmp_path):
    workspace, runtime = tmp_path / "workspace", tmp_path / "runtime"
    service = create_agent_service(workspace, runtime)
    try:
        session = await service.create_session()
        session = await service.set_title(session["session_id"], "重启前的对话")
    finally:
        await service.close()

    restored = create_agent_service(workspace, runtime)
    try:
        await restored.initialize()
        result = await CommandDispatcher(restored).dispatch(AgentCommand(text="/resume"))
        assert result["kind"] == "sessions"
        assert result["result"] == [session]
    finally:
        await restored.close()
