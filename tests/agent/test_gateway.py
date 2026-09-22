from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from logagent.agent.config import AgentConfig
from logagent.agent.gateway import InvocationSnapshot, PluginGateway
from logagent.collection.manager import CollectorManager
from logagent.config.views import (
    ChannelRegister,
    CollectorRegister,
    ToolRegister,
    channel_registration,
    collector_registration,
)
from logagent.errors import LogAgentError
from logagent.models import (
    ChannelConfig,
    CollectionContext,
    CollectorOutput,
    DeliveryResult,
    SourceConfig,
)
from logagent.schema import validate_instance


class Collector:
    name = "example"
    description = "Example source"
    execution = "read"
    count_unit = "records"
    options_schema = {"type": "object", "properties": {
        "account": {"type": "string", "description": "Fixed account"},
        "limit": {"$ref": "#/$defs/count", "description": "Count",
                  "x-logagent-workflow": True, "default": 999},
    }, "$defs": {"count": {"type": "integer", "minimum": 1}},
        "required": ["account", "limit"], "additionalProperties": False}
    setters_schema = {"type": "object", "properties": {
        "fields": {"type": "array", "items": {"type": "string"}, "description": "Fields"},
    }, "additionalProperties": False}

    def __init__(self):
        self.calls = []

    async def collect(self, options, setters, context):
        self.calls.append((options, setters))
        return CollectorOutput(status="success", text="one", count=1)


class Channel:
    name = "example"
    description = "Example channel"
    capabilities = ["notification"]
    options_schema = {"type": "object", "properties": {
        "account": {"type": "string", "description": "Fixed account"},
        "recipient": {"type": "string", "description": "Recipient", "x-logagent-workflow": True},
    }, "required": ["account", "recipient"], "additionalProperties": False}

    async def create(self, options, context):
        raise AssertionError("Gateway must use the manager")


def setup_gateway(tmp_path):
    collector = Collector()
    sources = CollectorRegister({"example": collector_registration(collector, "test")})
    channels = ChannelRegister({"example": channel_registration(Channel(), "test")})
    snapshot = InvocationSnapshot(1, {
        "sources": {"logs": SourceConfig(id="logs", collector="example",
                                        options={"account": "private", "limit": 5},
                                        setters={"fields": ["old"]})},
        "channels": {"mail": ChannelConfig(id="mail", channel="example",
                                         options={"account": "private", "recipient": "saved"})},
    }, sources, channels, ToolRegister())
    channel_manager = SimpleNamespace(send=AsyncMock(side_effect=lambda config, notification:
        DeliveryResult(channel_id=config.id, output_id=notification.output_id,
                       status="success", attempts=1)))
    gateway = PluginGateway(snapshot, collectors=CollectorManager(sources),
                            channels=channel_manager, data_dir=tmp_path)
    context = SimpleNamespace(config=AgentConfig(), session_id="session", turn_id="turn",
                              tool_call_id="provider/call:123",
                              collection=CollectionContext(workflow_id="agent", session_id="session"))
    return gateway, context, collector, channel_manager


async def test_gateway_discovers_and_projects_local_references_without_account_values(tmp_path):
    gateway, context, _, _ = setup_gateway(tmp_path)
    first = gateway.listing(page_size=1)
    assert len(first["entries"]) == 1 and first["next_cursor"] == 1
    assert gateway.execution({"action": "call", "target": "sources:logs"}) == "read"
    assert gateway.execution({"action": "call", "target": "channels:mail"}) == "exclusive"
    schema = gateway.schema("sources:logs")
    assert "private" not in str(schema)
    assert schema["properties"]["options"]["properties"]["limit"]["default"] == 5
    validate_instance({"options": {"limit": 2}}, schema)
    with pytest.raises(LogAgentError):
        validate_instance({"options": {"limit": "bad"}}, schema)
    with pytest.raises(LogAgentError):
        await gateway.invoke({"action": "call", "target": "sources:unknown"}, context)


async def test_gateway_calls_once_preserves_saved_defaults_and_explicit_empty_setters(tmp_path):
    gateway, context, collector, _ = setup_gateway(tmp_path)
    result = await gateway.invoke({"action": "call", "target": "sources:logs",
                                   "arguments": {"setters": {"fields": []}}}, context)
    assert result["status"] == "success"
    assert collector.calls == [({"account": "private", "limit": 5}, {"fields": []})]
    with pytest.raises(LogAgentError) as error:
        await gateway.invoke({"action": "call", "target": "sources:logs",
                              "arguments": {"options": {"account": "override"}}}, context)
    assert error.value.details["errors"][0]["reason"] == "instance_only"
    assert len(collector.calls) == 1


async def test_gateway_channel_ids_are_runtime_owned_and_only_one_send_occurs(tmp_path):
    gateway, context, _, channels = setup_gateway(tmp_path)
    arguments = {"action": "call", "target": "channels:mail", "arguments": {
        "options": {"recipient": "new"}, "notification": {"title": "Report", "text": "Body"}}}
    result = await gateway.invoke(arguments, context)
    assert result["status"] == "success"
    assert channels.send.await_count == 1
    config, notification = channels.send.call_args.args
    assert config.options == {"account": "private", "recipient": "new"}
    assert notification.session_id == "session" and len(notification.output_id) == 64
    arguments["arguments"]["notification"]["session_id"] = "forged"
    with pytest.raises(LogAgentError):
        await gateway.invoke(arguments, context)
    assert channels.send.await_count == 1
