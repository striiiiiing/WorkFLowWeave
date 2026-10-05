"""Provider persistence and model discovery use separate paths."""

import pytest
from fastapi.testclient import TestClient

from logagent.ai import AIService, OpenAIChannelFactory
from logagent.ai.channels import OpenAIChannel
from logagent.ai.errors import ModelError
from logagent.errors import LogAgentError
from logagent.interaction.app import create_app
from logagent.lifecycle import ApplicationLifecycle
from logagent.models import AIConfig, SystemConfig

pytestmark = pytest.mark.usefixtures("installed_plugins")


def test_save_without_models_and_check_failure_do_not_block_persistence(tmp_path, monkeypatch):
    calls = []

    async def unavailable(self, config):
        calls.append(config.id)
        raise LogAgentError("ai_http_error", "上游返回 HTTP 405")

    monkeypatch.setattr(AIService, "list_models", unavailable)
    owner = ApplicationLifecycle(SystemConfig(
        data_dir=str(tmp_path / "data"), plugin_dir=str(tmp_path / "plugins"),
    ))
    with TestClient(create_app(owner)) as client:
        encrypted = client.post("/api/credentials/protect", json={"plaintext": "test-only-key"})
        assert encrypted.status_code == 200
        payload = {
            "id": "provider", "provider": "http", "base_url": "http://127.0.0.1:1/v1",
            "api_key": encrypted.json(),
        }
        saved = client.post("/api/ai", json=payload)
        assert saved.status_code == 201, saved.text
        assert saved.json()["models"] == {}
        assert calls == []
        check = client.post("/api/ai/provider/check-connection")
        assert check.status_code == 500
        assert "405" in check.json()["error"]["message"]
        assert calls == ["provider"]
        assert client.get("/api/ai/provider").json() == saved.json()
        assert client.put("/api/ai/provider", json=payload).status_code == 200
        assert calls == ["provider"]

        async def available(self, config):
            return ["model-a", "model-b"]

        monkeypatch.setattr(AIService, "list_models", available)
        check = client.post("/api/ai/provider/check-connection")
        assert check.status_code == 200
        assert check.json() == ["model-a", "model-b"]
        assert check.headers["cache-control"] == "no-store"
        assert client.get("/api/ai/provider").json()["models"] == {}


def test_provider_without_models_cannot_execute_an_unconfigured_model():
    service = AIService(channel_factories={"http": OpenAIChannelFactory()})
    config = AIConfig(id="provider", provider="http", base_url="http://127.0.0.1:1/v1")
    service.validate(config)
    with pytest.raises(LogAgentError, match="model 不存在"):
        service.validate(config, "unconfigured")


def test_discover_unsaved_provider_resolves_protected_credential_without_persisting(tmp_path, monkeypatch):
    calls = []

    async def list_models(self, credential):
        calls.append((self.base_url, credential))
        return ["model-a", "model-b"]

    monkeypatch.setattr(OpenAIChannel, "list_models", list_models)
    owner = ApplicationLifecycle(SystemConfig(
        data_dir=str(tmp_path / "data"), plugin_dir=str(tmp_path / "plugins"),
    ))
    with TestClient(create_app(owner)) as client:
        protected = client.post("/api/credentials/protect", json={"plaintext": "draft-secret"})
        assert protected.status_code == 200
        payload = {
            "id": "draft", "provider": "http", "base_url": "http://127.0.0.1:1/v1",
            "api_key": protected.json(), "timeout": 2,
        }
        response = client.post("/api/ai/discover-models", json=payload)
        assert response.status_code == 200, response.text
        assert response.json() == ["model-a", "model-b"]
        assert response.headers["cache-control"] == "no-store"
        assert calls == [("http://127.0.0.1:1/v1/", "draft-secret")]
        assert client.get("/api/ai").json() == []
        assert "draft-secret" not in response.text


def test_discover_uses_current_draft_without_changing_saved_provider(tmp_path, monkeypatch):
    seen = []

    async def list_models(self, config):
        seen.append(config.model_dump(mode="json"))
        return ["draft-model"]

    monkeypatch.setattr(AIService, "list_models", list_models)
    owner = ApplicationLifecycle(SystemConfig(
        data_dir=str(tmp_path / "data"), plugin_dir=str(tmp_path / "plugins"),
    ))
    with TestClient(create_app(owner)) as client:
        saved = {
            "id": "provider", "provider": "http", "base_url": "http://127.0.0.1:1/v1",
            "models": {"saved-model": {}},
        }
        assert client.post("/api/ai", json=saved).status_code == 201
        draft = {**saved, "base_url": "http://127.0.0.1:2/v1", "models": {}}
        response = client.post("/api/ai/discover-models", json=draft)
        assert response.status_code == 200
        assert response.json() == ["draft-model"]
        assert seen[0]["base_url"] == draft["base_url"]
        assert seen[0]["models"] == {}
        assert client.get("/api/ai/provider").json()["models"] == saved["models"]
        assert client.get("/api/ai/provider").json()["base_url"] == saved["base_url"]
        assert client.post("/api/ai/provider/test-model", json={"model": "saved-model"}).status_code == 404


def test_discover_reports_upstream_failure(tmp_path, monkeypatch):
    async def unavailable(self, credential):
        raise ModelError("invalid_response", "模型列表响应缺少 data 数组")

    monkeypatch.setattr(OpenAIChannel, "list_models", unavailable)
    owner = ApplicationLifecycle(SystemConfig(
        data_dir=str(tmp_path / "data"), plugin_dir=str(tmp_path / "plugins"),
    ))
    with TestClient(create_app(owner)) as client:
        response = client.post("/api/ai/discover-models", json={
            "id": "draft", "provider": "http", "base_url": "http://127.0.0.1:1/v1",
            "retries": 0,
        })
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "invalid_response"
        assert client.get("/api/ai").json() == []
