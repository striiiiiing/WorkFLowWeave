"""Authenticated credential encryption; decryption never creates replacement keys."""

from __future__ import annotations

import asyncio
import hashlib
import os
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from pydantic import TypeAdapter, ValidationError

from workflowweave.config.reader import read_json
from workflowweave.config.store import _Resources
from workflowweave.errors import WorkFLowWeaveError, validation_error
from workflowweave.models import Credential, EncryptedCredential, SystemConfig

_CREDENTIAL = TypeAdapter(Credential)


def _contains_encrypted(value) -> bool:
    if isinstance(value, dict):
        return value.get("kind") == "encrypted" or any(_contains_encrypted(v) for v in value.values())
    return isinstance(value, list) and any(_contains_encrypted(v) for v in value)


class CredentialManager:
    def __init__(self, config: SystemConfig, *, resources_path: str | Path | None = None):
        self._key_env = config.master_key_env
        self._key_file = Path(config.master_key_file)
        if not self._key_file.is_absolute():
            self._key_file = Path(config.data_dir) / self._key_file
        self._key_history = self._key_file.with_name(self._key_file.name + ".initialized")
        self._resources = Path(resources_path or Path(config.data_dir) / "resources.json")
        self._lock = threading.Lock()

    def _record_key_use(self) -> None:
        """Retain first-use evidence even when resources or the key are removed."""
        try:
            self._key_history.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(self._key_history, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return
        except OSError:
            raise WorkFLowWeaveError("credential_key_unavailable", "无法记录主密钥使用状态") from None
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(b"WorkFLowWeave credential key has been used. Do not regenerate.\n")
                stream.flush()
                os.fsync(stream.fileno())
        except OSError:
            raise WorkFLowWeaveError("credential_key_unavailable", "主密钥使用状态写入失败") from None

    def _read_key(self, *, create: bool) -> bytes:
        supplied = os.environ.get(self._key_env)
        if supplied is not None:
            try:
                return supplied.encode("ascii")
            except UnicodeError:
                raise WorkFLowWeaveError("credential_key_invalid", "主密钥格式无效") from None
        try:
            return self._key_file.read_bytes()
        except FileNotFoundError:
            if not create or self._key_file.is_symlink():
                raise WorkFLowWeaveError("credential_key_missing", "解密所需原主密钥不存在") from None
        except OSError:
            raise WorkFLowWeaveError("credential_key_unavailable", "主密钥文件无法读取") from None

        try:
            self._key_history.lstat()
        except FileNotFoundError:
            pass
        except OSError:
            raise WorkFLowWeaveError("credential_key_unavailable", "无法确认主密钥是否首次使用") from None
        else:
            raise WorkFLowWeaveError("credential_key_missing", "曾使用的主密钥不存在，不能生成替代密钥")

        # A corrupt/unreadable resource document is not evidence of first use.
        if self._resources.exists() or self._resources.is_symlink():
            document = read_json(self._resources)
            try:
                _Resources.model_validate(document)
            except ValidationError as exc:
                raise validation_error(exc) from None
            if _contains_encrypted(document):
                raise WorkFLowWeaveError("credential_key_missing", "已有密文缺少原主密钥，不能生成替代密钥")
        key = Fernet.generate_key()
        self._record_key_use()
        try:
            self._key_file.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(self._key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return self._read_key(create=False)
        except OSError:
            raise WorkFLowWeaveError("credential_key_unavailable", "无法创建主密钥文件") from None
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(key)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError:
            # Keep any partial file visible: a later call must report the damaged
            # key rather than silently overwrite it or claim encryption succeeded.
            raise WorkFLowWeaveError("credential_key_unavailable", "主密钥写入失败") from None
        return key

    def _cipher(self, *, create: bool):
        key = self._read_key(create=create)
        try:
            cipher = Fernet(key)
        except (ValueError, TypeError):
            raise WorkFLowWeaveError("credential_key_invalid", "主密钥格式无效") from None
        return cipher, hashlib.sha256(key).hexdigest()

    def protect(self, plaintext: str) -> EncryptedCredential:
        if not isinstance(plaintext, str) or not plaintext:
            raise WorkFLowWeaveError("invalid_credential", "待保护凭据必须为非空字符串")
        with self._lock:
            cipher, key_id = self._cipher(create=True)
            self._record_key_use()
            return EncryptedCredential(key_id=key_id, ciphertext=cipher.encrypt(plaintext.encode()).decode())

    def _resolve(self, credential: Credential) -> str:
        try:
            value = _CREDENTIAL.validate_python(credential)
        except ValidationError as exc:
            raise validation_error(exc) from None
        if value.kind == "env":
            secret = os.environ.get(value.name)
            if not secret:
                raise WorkFLowWeaveError("credential_missing", "凭据环境变量未提供有效值")
            return secret
        with self._lock:
            cipher, key_id = self._cipher(create=False)
            if value.key_id != key_id:
                raise WorkFLowWeaveError("credential_key_mismatch", "当前主密钥与密文不匹配")
            try:
                return cipher.decrypt(value.ciphertext.encode()).decode("utf-8")
            except (InvalidToken, UnicodeError, ValueError):
                raise WorkFLowWeaveError("credential_invalid", "凭据密文损坏或认证失败") from None

    async def resolve(self, credential: Credential) -> str:
        return await asyncio.to_thread(self._resolve, credential)
