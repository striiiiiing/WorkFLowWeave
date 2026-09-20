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
