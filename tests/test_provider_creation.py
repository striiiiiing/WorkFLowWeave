"""Provider persistence and optional connection checks use separate paths."""

import pytest
from fastapi.testclient import TestClient

from logagent.ai import AIService, OpenAIChannelFactory
from logagent.errors import LogAgentError
from logagent.interaction.app import create_app
from logagent.lifecycle import ApplicationLifecycle
from logagent.models import AIConfig, AnalysisResult, ErrorInfo, SystemConfig


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


def test_model_test_sends_hi_to_the_selected_model(tmp_path, monkeypatch):
    calls = []

    async def execute(self, config, prompt, input_text, *, model, task_id, context=None, on_cancel=None):
        calls.append((config.id, prompt, input_text, model, task_id))
        return AnalysisResult(task_id=task_id, status="success", text="Hi back")

    monkeypatch.setattr(AIService, "execute", execute)
    owner = ApplicationLifecycle(SystemConfig(
        data_dir=str(tmp_path / "data"), plugin_dir=str(tmp_path / "plugins"),
    ))
    with TestClient(create_app(owner)) as client:
        payload = {
            "id": "provider", "provider": "http", "base_url": "http://127.0.0.1:1/v1",
            "models": {"model-a": {}},
        }
        assert client.post("/api/ai", json=payload).status_code == 201
        response = client.post("/api/ai/provider/test-model", json={"model": "model-a"})
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "success"
        assert calls == [("provider", "{input}", "Hi", "model-a", "model-test")]


def test_model_test_keeps_unsuccessful_model_response_as_failure(tmp_path, monkeypatch):
    async def execute(self, config, prompt, input_text, *, model, task_id, context=None, on_cancel=None):
        return AnalysisResult(
            task_id=task_id,
            status="failed",
            error=ErrorInfo(code="provider_rejected", message="模型拒绝请求", details={}),
        )

    monkeypatch.setattr(AIService, "execute", execute)
    owner = ApplicationLifecycle(SystemConfig(
        data_dir=str(tmp_path / "data"), plugin_dir=str(tmp_path / "plugins"),
    ))
    with TestClient(create_app(owner)) as client:
        payload = {
            "id": "provider", "provider": "http", "base_url": "http://127.0.0.1:1/v1",
            "models": {"model-a": {}},
        }
        assert client.post("/api/ai", json=payload).status_code == 201
        response = client.post("/api/ai/provider/test-model", json={"model": "model-a"})
        assert response.status_code == 200
        assert response.json()["status"] == "failed"
        assert response.json()["error"]["code"] == "provider_rejected"
