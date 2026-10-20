"""Installed SPA dispatch preserves API and asset error semantics."""

import pytest
from fastapi.testclient import TestClient

from workflowweave.interaction.app import create_app


@pytest.fixture
def web_client(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>packaged-app</html>")
    (tmp_path / "assets/app.js").write_text("export default 42")
    return TestClient(create_app(frontend_dir=tmp_path))


@pytest.mark.parametrize("path", ["/", "/agents/session-1", "/workflows/example/edit"])
def test_page_navigation_loads_packaged_entry(web_client, path):
    response = web_client.get(path)
    assert response.status_code == 200
    assert response.text == "<html>packaged-app</html>"
    assert response.headers["content-type"].startswith("text/html")
    assert web_client.head(path).content == b""


def test_real_asset_and_openapi_still_work(web_client):
    asset = web_client.get("/assets/app.js")
    assert asset.status_code == 200
    assert asset.text == "export default 42"
    assert "javascript" in asset.headers["content-type"]
    assert web_client.get("/openapi.json").json()["info"]["title"] == "WorkFLowWeave API"


@pytest.mark.parametrize("path", [
    "/api/missing/path/extra", "/api", "/assets/missing.js", "/assets/missing",
    "/missing.css", "/docs/missing", "/redoc/missing",
])
def test_unknown_api_and_assets_are_not_spa_pages(web_client, path):
    assert web_client.get(path).status_code == 404


def test_source_checkout_without_bundle_keeps_api_available(tmp_path):
    client = TestClient(create_app(frontend_dir=tmp_path))
    assert client.get("/").status_code == 404
    assert client.get("/openapi.json").status_code == 200


def test_missing_node_does_not_block_service(tmp_path, monkeypatch, caplog):
    from workflowweave.lifecycle import ApplicationLifecycle
    from workflowweave.models import SystemConfig
    from workflowweave.plugins.channel.wechat_openclaw import node

    monkeypatch.setattr(node, "resolve_node", lambda: _missing_node())
    config = SystemConfig(
        data_dir=str(tmp_path / "data"), plugin_dir=str(tmp_path / "plugins"),
        master_key_file=str(tmp_path / "master.key"),
    )
    with TestClient(create_app(ApplicationLifecycle(config))) as client:
        assert client.get("/api/health").json()["status"] == "ready"
    assert "wechat_node_unavailable" in caplog.text


def _missing_node():
    from workflowweave.channel.errors import ChannelDeliveryError

    raise ChannelDeliveryError("wechat_node_unavailable", "Node.js unavailable")
