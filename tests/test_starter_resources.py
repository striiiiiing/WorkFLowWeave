"""首次启动默认资源的跨模块集成测试。

以临时目录启动真实 ApplicationLifecycle 和 FastAPI TestClient，检查内置插件、
默认采集源及文件渠道可通过 API 查询；删除默认源后重启，断言不会重新生成。
覆盖配置、装配与交互边界，不调用远端模型或发送邮件。
"""

from fastapi.testclient import TestClient

from logagent.interaction.app import create_app
from logagent.lifecycle import ApplicationLifecycle
from logagent.models import SystemConfig


def test_starter_resources_are_selectable_and_deleted_defaults_stay_deleted(tmp_path):
    config = SystemConfig(
        data_dir=str(tmp_path / "data"), plugin_dir=str(tmp_path / "plugins"),
        master_key_file=str(tmp_path / "master.key"),
    )
    with TestClient(create_app(ApplicationLifecycle(config))) as client:
        plugins = client.get("/api/plugins").json()
        assert {(p["kind"], p["name"]) for p in plugins} == {
            ("collector", "mock"), ("collector", "logs"), ("collector", "history"),
            ("channel", "mock"), ("channel", "email"),
        }
        sources = client.get("/api/sources").json()
        assert {s["id"] for s in sources} == {
            "default_mock", "default_logs", "default_history",
        }
        channels = client.get("/api/channels").json()
        assert channels[0]["id"] == "default_file"
        assert channels[0]["options"]["path"] == str(tmp_path / "data/notifications.txt")
        assert client.delete("/api/sources/default_mock").status_code == 204
    with TestClient(create_app(ApplicationLifecycle(config))) as client:
        assert "default_mock" not in {s["id"] for s in client.get("/api/sources").json()}
