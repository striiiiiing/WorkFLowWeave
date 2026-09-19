"""Credential boundaries never expose or silently replace secret material."""

import asyncio
import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from logagent.config import CredentialManager, ResourceStore
from logagent.errors import LogAgentError
from logagent.models import AIConfig, EnvironmentCredential, SystemConfig


def manager(tmp_path):
    return CredentialManager(SystemConfig(data_dir=str(tmp_path)))


async def test_env_resolves_at_use_without_creating_key(tmp_path, monkeypatch):
    credentials = manager(tmp_path)
    reference = EnvironmentCredential(name="TEST_LOGAGENT_SECRET")
    monkeypatch.setenv(reference.name, "first-secret")
    assert await credentials.resolve(reference) == "first-secret"
    monkeypatch.setenv(reference.name, "changed-secret")
    assert await credentials.resolve(reference) == "changed-secret"
    monkeypatch.delenv(reference.name)
    with pytest.raises(LogAgentError) as caught:
        await credentials.resolve(reference)
    assert "secret" not in caught.value.info.model_dump_json()
    assert not (tmp_path / "master.key").exists()


async def test_encryption_round_trip_and_file_permissions(tmp_path, monkeypatch):
    monkeypatch.delenv("LOGAGENT_MASTER_KEY", raising=False)
    credentials = manager(tmp_path)
    value = credentials.protect("凭据-secret")
    key_path = tmp_path / "master.key"
    assert key_path.stat().st_mode & 0o777 == 0o600
    assert "凭据-secret" not in value.model_dump_json()
    assert await manager(tmp_path).resolve(value) == "凭据-secret"
    original = key_path.read_bytes()
    second = credentials.protect("another")
    assert key_path.read_bytes() == original
    assert second.key_id == value.key_id
    store = ResourceStore(tmp_path / "resources.json")
    store.save("ai", AIConfig(id="ai", provider="mock", models={"model": {}}, api_key=value))
    assert "凭据-secret" not in await asyncio.to_thread(Path(store.location).read_text)


def test_lost_key_cannot_be_regenerated_even_without_saved_resources(tmp_path, monkeypatch):
    monkeypatch.delenv("LOGAGENT_MASTER_KEY", raising=False)
    credentials = manager(tmp_path)
    credentials.protect("not-yet-persisted")
    (tmp_path / "master.key").unlink()
    for candidate in (credentials, manager(tmp_path)):
        with pytest.raises(LogAgentError) as caught:
            candidate.protect("new-secret")
        assert caught.value.code == "credential_key_missing"
    assert not (tmp_path / "master.key").exists()


async def test_env_master_key_has_priority_without_file_creation(tmp_path, monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("LOGAGENT_MASTER_KEY", key)
    credentials = manager(tmp_path)
    value = credentials.protect("private")
    assert await credentials.resolve(value) == "private"
    assert not (tmp_path / "master.key").exists()


async def test_decryption_never_generates_key_and_protect_checks_existing_ciphertext(tmp_path, monkeypatch):
    monkeypatch.delenv("LOGAGENT_MASTER_KEY", raising=False)
    credentials = manager(tmp_path)
    value = credentials.protect("secret")
    store = ResourceStore(tmp_path / "resources.json")
    store.save("ai", AIConfig(id="ai", provider="mock", models={"model": {}}, api_key=value))
    (tmp_path / "master.key").unlink()
    for operation in (lambda: credentials.protect("new"),):
        with pytest.raises(LogAgentError) as caught:
            operation()
        assert caught.value.code == "credential_key_missing"
    with pytest.raises(LogAgentError):
        await credentials.resolve(value)
    assert not (tmp_path / "master.key").exists()


@pytest.mark.parametrize("content", [b"broken", b"", b"not-a-key-private"])
async def test_invalid_existing_key_is_not_replaced(tmp_path, monkeypatch, content):
    monkeypatch.delenv("LOGAGENT_MASTER_KEY", raising=False)
    key_path = tmp_path / "master.key"
    key_path.write_bytes(content)
    with pytest.raises(LogAgentError) as caught:
        manager(tmp_path).protect("new-secret")
    assert caught.value.code == "credential_key_invalid"
    assert "private" not in caught.value.info.model_dump_json()
    assert key_path.read_bytes() == content


@pytest.mark.parametrize("content", ["not JSON", "{}", '{"format_version":99}'])
async def test_unreadable_or_unrecognized_resources_prevent_key_generation(tmp_path, content):
    (tmp_path / "resources.json").write_text(content)
    with pytest.raises(LogAgentError):
        manager(tmp_path).protect("secret")
    assert not (tmp_path / "master.key").exists()


async def test_tampering_and_wrong_key_are_explicit_and_redacted(tmp_path, monkeypatch):
    monkeypatch.delenv("LOGAGENT_MASTER_KEY", raising=False)
    credentials = manager(tmp_path)
    value = credentials.protect("SECRET_INPUT")
    broken = value.model_copy(update={"ciphertext": "SECRET_CIPHERTEXT"})
    with pytest.raises(LogAgentError) as caught:
        await credentials.resolve(broken)
    assert caught.value.code == "credential_invalid"
    assert "SECRET" not in caught.value.info.model_dump_json()
    monkeypatch.setenv("LOGAGENT_MASTER_KEY", Fernet.generate_key().decode())
    with pytest.raises(LogAgentError) as caught:
        await credentials.resolve(value)
    assert caught.value.code == "credential_key_mismatch"


async def test_invalid_env_key_does_not_fall_back_to_valid_file(tmp_path, monkeypatch):
    monkeypatch.delenv("LOGAGENT_MASTER_KEY", raising=False)
    credentials = manager(tmp_path)
    value = credentials.protect("secret")
    monkeypatch.setenv("LOGAGENT_MASTER_KEY", "invalid-env-secret")
    with pytest.raises(LogAgentError) as caught:
        await credentials.resolve(value)
    assert caught.value.code == "credential_key_invalid"
    assert "invalid-env-secret" not in str(caught.value)


async def test_key_file_io_failure_is_not_masked(tmp_path, monkeypatch):
    credentials = manager(tmp_path)
    def fail(*args, **kwargs):
        raise PermissionError("PRIVATE_PATH")
    monkeypatch.setattr(os, "open", fail)
    with pytest.raises(LogAgentError) as caught:
        credentials.protect("private")
    assert caught.value.code == "credential_key_unavailable"
    assert "PRIVATE_PATH" not in caught.value.info.model_dump_json()
