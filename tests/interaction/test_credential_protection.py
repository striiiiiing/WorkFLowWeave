"""Credential HTTP projection uses the real encryption manager without plaintext responses."""
import asyncio

import pytest

from workflowweave.config.credentials import CredentialManager
from workflowweave.interaction.schemas import ProtectCredentialRequest
from workflowweave.models import EncryptedCredential, SystemConfig
from tests.interaction.test_interaction import Lifecycle, _client


def lifecycle_with_credentials(tmp_path):
    lifecycle = Lifecycle()
    lifecycle.services.credentials = CredentialManager(SystemConfig(data_dir=str(tmp_path)))
    return lifecycle


def test_protect_roundtrip_and_save_without_plaintext(tmp_path, caplog):
    lifecycle = lifecycle_with_credentials(tmp_path)
    secret = "test-only-api-key"
    with _client(lifecycle) as client:
        protected = client.post("/api/credentials/protect", json={"plaintext": secret})
        assert protected.status_code == 200, protected.text
        assert protected.headers["cache-control"] == "no-store"
        assert secret not in protected.text
        credential = EncryptedCredential.model_validate(protected.json())
        assert asyncio.run(lifecycle.services.credentials.resolve(credential)) == secret
        saved = client.post("/api/ai", json={"id": "ai", "provider": "http", "models": {"model": {}}, "api_key": protected.json()})
        assert saved.status_code == 201
        assert secret not in saved.text
        assert client.get("/api/ai/ai").json()["api_key"] == protected.json()
    assert secret not in caplog.text
    assert secret not in repr(ProtectCredentialRequest(plaintext=secret))


@pytest.mark.parametrize("payload", [{"plaintext": ""}, {"plaintext": 123}, {}, {"plaintext": "secret", "unknown": "secret"}])
def test_invalid_protection_requests_are_explicit_and_redacted(tmp_path, payload):
    with _client(lifecycle_with_credentials(tmp_path)) as client:
        result = client.post("/api/credentials/protect", json=payload)
    assert result.status_code == 422
    assert "secret" not in result.text
    assert "input" not in str(result.json()["error"]["details"])


def test_missing_previously_used_key_fails_without_replacement(tmp_path):
    lifecycle = lifecycle_with_credentials(tmp_path)
    with _client(lifecycle) as client:
        result = client.post("/api/credentials/protect", json={"plaintext": "first-key"})
        assert result.status_code == 200
        (tmp_path / "master.key").unlink()
        result = client.post("/api/credentials/protect", json={"plaintext": "second-key"})
    assert result.status_code >= 400
    assert result.json()["error"]["code"] == "credential_key_missing"
    assert "second-key" not in result.text
    assert not (tmp_path / "master.key").exists()
