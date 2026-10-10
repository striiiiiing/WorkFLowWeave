"""Startup keeps healthy Agent channels available when one receiver fails."""

import httpx
import pytest

from tests.fixtures.plugin_helpers import install_test_channel_plugin
from workflowweave.channel import builtin_channels
from workflowweave.channel.manager import ChannelManager
from workflowweave.config import PluginRegistry, ResourceStore
from workflowweave.interaction.app import create_app
from workflowweave.lifecycle import ApplicationLifecycle
from workflowweave.models import ChannelConfig, SystemConfig


@pytest.mark.asyncio
async def test_failed_channel_receiver_does_not_abort_application_startup(
    tmp_path, monkeypatch,
):
    config = SystemConfig(
        data_dir=str(tmp_path / "data"),
        plugin_dir=str(tmp_path / "plugins"),
        builtin_plugin_dir=str(tmp_path / "builtin"),
    )
    install_test_channel_plugin(config.plugin_dir)
    registry = PluginRegistry(builtin_channels=builtin_channels())
    await registry.discover_plugins(config)
    resources = ResourceStore(
        f"{config.data_dir}/resources.json",
        channel_register=registry.channelRegister,
        data_dir=config.data_dir,
    )
    healthy = ChannelConfig(
        id="test-good",
        channel="test",
        agent_enabled=True,
        options={"target": "healthy"},
    )
    failing = ChannelConfig(
        id="test-bad",
        channel="test",
        agent_enabled=True,
        options={"target": "failing"},
    )
    resources.save("channels", healthy)
    resources.save("channels", failing)

    start_receiving = ChannelManager.start_receiving

    async def fail_one_receiver(self, channel_config, handler, *, temporary=False):
        if channel_config.id == failing.id:
            raise RuntimeError("simulated receiver handshake failure")
        await start_receiving(self, channel_config, handler, temporary=temporary)

    monkeypatch.setattr(ChannelManager, "start_receiving", fail_one_receiver)
    lifecycle = ApplicationLifecycle(config, channel_factories={})

    try:
        services = await lifecycle.start()

        assert set(services.channels.configs) == {healthy.id}
        assert services.channels.receiver(healthy).receiver_status() == {
            "state": "running",
            "error": None,
        }
        assert services.resources.get("channels", failing.id) == failing
        health = await lifecycle.health()
        assert health.status == "degraded"
        assert health.accepting_runs is True
        plugins = next(item for item in health.components if item.component == "plugins")
        assert plugins.required is False
        assert plugins.error.details["capability_errors"] == [
            services.channels.receiver_errors[failing.id].model_dump(mode="json"),
        ]
        assert "simulated receiver handshake failure" not in health.model_dump_json()
        app = create_app(lifecycle)
        app.state.services = services
        app.state.lifecycle = lifecycle
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            response = await client.get("/api/health")
            assert response.status_code == 200
            assert response.json()["status"] == "degraded"
            response = await client.post("/api/channels/web/commands", json={
                "action": "new", "request_id": "optional-channel-failed",
            })
            assert response.status_code == 202
            assert response.json()["result"]["session_id"]

        monkeypatch.setattr(ChannelManager, "start_receiving", start_receiving)
        await services.channels.configure(services.resources.list("channels"))
        assert services.channels.receiver_errors == {}
        assert set(services.channels.configs) == {healthy.id, failing.id}
        health = await lifecycle.health()
        assert health.status == "ready", health.model_dump_json()
    finally:
        await lifecycle.shutdown()
