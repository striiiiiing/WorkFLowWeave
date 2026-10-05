"""Open synthetic e71341c persistence with the redesigned runtime."""

import json
import shutil
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from logagent.interaction.fastapi.agent import create_agent_service
from tests.agent.helpers import ScriptedModel

FIXTURE = Path(__file__).parents[1] / "fixtures" / "agent_pre_redesign"


@pytest.mark.asyncio
async def test_old_sessions_checkpoint_fork_and_unknown_effect_are_preserved(tmp_path):
    shutil.copytree(FIXTURE, tmp_path, dirs_exist_ok=True)
    expected = json.loads((tmp_path / "expected.json").read_text())
    model = ScriptedModel(responses=[AIMessage(content="continued fixture")])
    service = create_agent_service(
        tmp_path / "workspace", tmp_path / "runtime", model_provider=lambda _: model,
    )
    try:
        await service.initialize()
        for sid, identifiers in expected["events"].items():
            events = await service.events(sid)
            assert [event["id"] for event in events[:len(identifiers)]] == identifiers
        completed = await service.get_session(expected["completed"])
        child = await service.get_session(expected["fork"])
        assert completed["status"] == "completed"
        assert child["parent_session_id"] == expected["completed"]
        assert child["parent_turn_id"] == expected["completed_turn"]
        assert (await service.source(child["session_id"]))["workflow_session_id"] == "workflow_fixture"
        unknown = await service.events(expected["interrupted"])
        assert any(event["type"] == "tool.outcome_unknown" for event in unknown)
        assert (await service.get_session(expected["interrupted"]))["status"] == "interrupted"
        accepted = await service.submit(expected["completed"], "continue", request_id="post_redesign")
        assert (await service.wait(accepted["turn_id"]))["status"] == "completed"
        assert len(model.seen) == 1
        assert (await service.get_session(child["session_id"]))["turn_id"] == child["turn_id"]
    finally:
        await service.close()
