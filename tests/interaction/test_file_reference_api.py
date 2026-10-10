from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from workflowweave.collection import CollectorManager, FileReferenceStore
from workflowweave.config import ResourceStore
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.interaction.app import create_app
from workflowweave.interaction.dependencies import get_services


@pytest.fixture
def api(tmp_path):
    files = FileReferenceStore(tmp_path / "data")
    collectors = CollectorManager(None, files)
    resources = ResourceStore(tmp_path / "resources.json", validators={"sources": collectors.validate})
    services = SimpleNamespace(
        collectors=collectors, resources=resources, log_path=None,
        credentials=None, session_view=None,
    )
    app = create_app()
    app.dependency_overrides[get_services] = lambda: services
    client = TestClient(app)
    yield client, files
    client.close()


def test_create_text_reference_and_collect_after_external_edit(api):
    client, files = api
    response = client.post("/api/collection/files/text", json={
        "path": "notes/example.txt", "file_type": "text", "text": "正文\r\n tail ",
    })
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    reference = response.json()
    assert reference == {"kind": "file", "file_type": "text", "path": "notes/example.txt"}
    assert (files.root / reference["path"]).read_bytes() == "正文\r\n tail ".encode()
    saved = client.post("/api/sources", json={"id": "file", "call": reference})
    assert saved.status_code == 201
    assert "text" not in saved.json()["call"]
    first = client.post("/api/sources/file/collect", json={})
    assert first.json()["raw"] == {"text": "正文\r\n tail "}
    (files.root / reference["path"]).write_bytes(b"updated")
    second = client.post("/api/sources/file/collect", json={})
    assert second.json()["raw"] == {"text": "updated"}
    assert client.get("/api/sources/file/call-schema").json()["properties"] == {}
    rejected = client.post("/api/sources/file/collect", json={"arguments": {"path": "other"}})
    assert rejected.status_code == 422


@pytest.mark.parametrize("content", [b"", "中文\r\n\r\n".encode()])
def test_import_preserves_original_bytes_including_empty_file(api, content):
    client, files = api
    response = client.post("/api/collection/files/import", params={"path": "imported.md", "file_type": "text"},
                           content=content, headers={"content-type": "application/octet-stream"})
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    assert (files.root / "imported.md").read_bytes() == content


def test_api_type_path_encoding_and_conflict_errors(api):
    client, files = api
    base = {"path": "example.txt", "file_type": "text", "text": "first"}
    assert client.post("/api/collection/files/text", json=base).status_code == 201
    conflict = client.post("/api/collection/files/text", json={**base, "text": "replacement"})
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "file_conflict"
    assert (files.root / "example.txt").read_bytes() == b"first"
    assert client.post("/api/collection/files/text", json={**base, "file_type": "pdf"}).status_code == 422
    assert client.post("/api/collection/files/text", json={"path": "other", "text": "x"}).status_code == 422
    assert client.post("/api/collection/files/text", json={**base, "path": "../secret"}).status_code == 403
    invalid = client.post("/api/collection/files/import", params={"path": "invalid", "file_type": "text"},
                          content=b"\xff", headers={"content-type": "application/octet-stream"})
    assert invalid.status_code == 422
    assert not (files.root / "invalid").exists()


def test_openapi_and_reference_saving_do_not_require_file_to_exist(api):
    client, _ = api
    assert client.get("/openapi.json").status_code == 200
    saved = client.post("/api/sources", json={
        "id": "future", "call": {"kind": "file", "file_type": "text", "path": "future.txt"},
    })
    assert saved.status_code == 201
    missing = client.post("/api/sources/future/collect", json={})
    assert missing.status_code == 200
    assert missing.json()["status"] == "failed"
    assert missing.json()["error"]["code"] == "file_missing"


def test_detached_workflow_source_uses_the_same_path_boundary(api):
    client, _ = api
    assert client.post("/api/ai", json={
        "id": "ai", "provider": "test", "models": {"test": {}},
    }).status_code == 201
    # The store validates detached sources through the same collector validator.
    services = client.app.dependency_overrides[get_services]()
    with pytest.raises(WorkFLowWeaveError) as exc:
        services.resources.save("workflows", {
            "id": "wf", "sources": ["local"],
            "analyses": [{"id": "a", "ai": "ai", "model": "test", "user_prompt": "analyze"}],
            "source_overrides": {"local": {"source": {
                "id": "local", "call": {"kind": "file", "file_type": "text", "path": "../secret"},
            }}},
        })
    assert exc.value.code == "path_forbidden"
