from fastapi.testclient import TestClient

from workflowweave.interaction.app import create_app
from workflowweave.lifecycle import ApplicationLifecycle
from workflowweave.models import SystemConfig


def test_real_lifecycle_injects_files_and_restart_reads_external_edits(tmp_path):
    config = SystemConfig(
        data_dir=str(tmp_path / "data"), plugin_dir=str(tmp_path / "plugins"),
        master_key_file=str(tmp_path / "master.key"),
    )
    with TestClient(create_app(ApplicationLifecycle(config))) as client:
        created = client.post("/api/collection/files/text", json={
            "path": "notes/example.txt", "file_type": "text", "text": "before restart",
        })
        assert created.status_code == 201
        assert client.post("/api/sources", json={"id": "file", "call": created.json()}).status_code == 201
        assert client.post("/api/sources/file/collect", json={}).json()["raw"] == {"text": "before restart"}
    path = tmp_path / "data/references/notes/example.txt"
    path.write_bytes(b"edited externally")
    with TestClient(create_app(ApplicationLifecycle(config))) as client:
        assert client.post("/api/sources/file/collect", json={}).json()["raw"] == {"text": "edited externally"}
