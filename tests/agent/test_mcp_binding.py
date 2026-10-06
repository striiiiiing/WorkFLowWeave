import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from workflowweave.agent.config import AgentConfig
from workflowweave.agent.integrations.mcp import MCPGateway
from workflowweave.agent.tools.builtin.mcp import plugin
from workflowweave.config.store import ResourceStore
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.interaction.fastapi.agent import create_agent_service
from workflowweave.mcp import MCPRuntime
from workflowweave.models import MCPServerConfig
from tests.agent.helpers import ScriptedModel
from tests.mcp.test_runtime import Connector


async def test_session_restores_original_scope_and_fork_preserves_it(tmp_path):
    resources = ResourceStore(tmp_path / "resources.json")
    old = MCPServerConfig(id="old", transport="stdio", command="old-command")
    resources.save("mcp_servers", old)
    binding = {"servers": {"old": old.model_dump(mode="json")}, "sources": [
        {"source": "failed_source", "server": "old", "tool": "echo"}]}
    async def reader(sid):
        return binding
    model = ScriptedModel(responses=[AIMessage(content="answer")])
    kwargs = dict(resources=resources, model_provider=lambda _: model,
                  mcp_runtime=MCPRuntime(Connector()), mcp_binding_reader=reader)
    service = create_agent_service(tmp_path / "workspace", tmp_path / "runtime", **kwargs)
    session = await service.create_session(workflow_session_id="run", workflow_result={"outputs": {"x": "result"}})
    sid = session["session_id"]
    resources.save("mcp_servers", old.model_copy(update={"command": "replacement"}))
    resources.save("mcp_servers", MCPServerConfig(id="new", transport="stdio", command="other"))
    gateway = service.resource_provider.capture(service.sessions[sid]).gateway
    assert set(gateway.scope) == {"old"} and gateway.scope["old"].command == "old-command"
    turn = await service.submit(sid, "continue", request_id="first")
    await service.wait(turn["turn_id"])
    child = await service.fork(sid)
    assert service.session_manager.bindings.read(child["session_id"]) == binding
    await service.close()
    restored = create_agent_service(tmp_path / "workspace", tmp_path / "runtime", **kwargs)
    await restored.initialize()
    try:
        assert restored.session_manager.bindings.read(sid) == binding
        assert restored.session_manager.bindings.read(child["session_id"]) == binding
        events = json.dumps(await restored.events(sid), ensure_ascii=False)
        assert "old-command" not in events and "replacement" not in events
    finally:
        await restored.close()


async def test_proxy_fixed_schema_direct_call_and_cli_empty_scope():
    connector = Connector()
    runtime = MCPRuntime(connector)
    server = MCPServerConfig(id="one", transport="stdio", command="echo")
    gateway = MCPGateway(runtime, {"servers": {"one": server.model_dump(mode="json")}})
    context = SimpleNamespace(config=AgentConfig(), session_id="s", turn_id="t", tool_call_id="c")
    assert "echo" not in json.dumps(plugin.input_schema)
    listing = await gateway.invoke({"action": "search", "query": "echo"}, context)
    assert listing["incomplete"] and connector.opens == 0
    output = await gateway.invoke({"action": "call", "server": "one", "tool": "echo",
                                   "arguments": {"value": "new args"}}, context)
    assert output["raw"]["content"][0]["text"] == "false"
    assert connector.calls == [("echo", {"value": "new args"})]
    empty = MCPGateway(runtime, {"servers": {}, "sources": []})
    with pytest.raises(WorkFLowWeaveError, match="范围"):
        await empty.invoke({"action": "call", "server": "one", "tool": "echo"}, context)
