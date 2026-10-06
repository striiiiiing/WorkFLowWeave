"""Static Agent graph ownership and runtime binding contracts."""

from langchain_core.messages import AIMessage

from workflowweave.agent.config import AgentConfig
from workflowweave.interaction.fastapi.agent import create_agent_service
from tests.agent.helpers import ScriptedModel


async def test_two_turns_reuse_the_composition_root_graph(tmp_path):
    service = create_agent_service(
        tmp_path / "workspace",
        tmp_path / "runtime",
        config=AgentConfig(),
        model_provider=lambda _: ScriptedModel(
            responses=[AIMessage(content="first"), AIMessage(content="second")],
        ),
    )
    try:
        await service.initialize()
        graph = service.runner.graph
        session = await service.create_session(model="scripted")
        first = await service.submit(session["session_id"], "one", request_id="one")
        await service.wait(first["turn_id"])
        second = await service.submit(session["session_id"], "two", request_id="two")
        await service.wait(second["turn_id"])
        assert service.runner.graph is graph
        assert service.runner.graph_builder.graph is graph
    finally:
        await service.close()
