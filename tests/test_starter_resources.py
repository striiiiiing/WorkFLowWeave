"""首次启动资源与插件默认值的跨模块集成测试。

以临时目录启动真实 ApplicationLifecycle 和 FastAPI TestClient，检查新安装不
预置 Source 或 Channel 资源，同时保留通用 Web 与 Agent 工具能力。
覆盖配置、装配与交互边界，不调用远端模型或发送邮件。
"""

from fastapi.testclient import TestClient

from workflowweave.interaction.app import create_app
from workflowweave.lifecycle import ApplicationLifecycle
from workflowweave.models import SystemConfig


def test_new_install_has_no_preconfigured_resources(tmp_path):
    config = SystemConfig(
        data_dir=str(tmp_path / "data"), plugin_dir=str(tmp_path / "plugins"),
        master_key_file=str(tmp_path / "master.key"),
    )
    with TestClient(create_app(ApplicationLifecycle(config))) as client:
        plugins = client.get("/api/plugins").json()
        plugin_ids = {(plugin["kind"], plugin["name"]) for plugin in plugins}
        assert {kind for kind, _ in plugin_ids} == {"channel", "tool"}
        assert ("channel", "web") in plugin_ids
        assert {("tool", name) for name in ("mcp", "read", "write", "grep", "shell")} <= plugin_ids
        assert client.get("/api/sources").json() == []
        assert client.get("/api/channels").json() == []
    with TestClient(create_app(ApplicationLifecycle(config))) as client:
        assert client.get("/api/sources").json() == []
        assert client.get("/api/channels").json() == []
