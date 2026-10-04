"""SMTP notification channel backed by :mod:`aiosmtplib`."""

from __future__ import annotations

import asyncio
import hashlib
from copy import deepcopy
from email.message import EmailMessage
from email.policy import SMTP, SMTPUTF8
from typing import Any

import aiosmtplib
from pydantic import TypeAdapter

from logagent.channel.context import remaining_delivery_time
from logagent.channel.errors import ChannelDeliveryError
from logagent.models import ChannelConfig, Credential, Notification
from logagent.schema import (
    resource_options_schema,
    split_options,
    validate_instance,
    validate_workflow_options,
)

_STOP_TIMEOUT = 5.0
_CREDENTIAL_SCHEMA = TypeAdapter(Credential).json_schema()
_ADDRESS = {
    "type": "string",
    "format": "email",
    "description": "单个邮箱地址",
    "pattern": r"^[^\s@<>,;]+@[^\s@<>,;]+$",
}
_OPTIONS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "$defs": _CREDENTIAL_SCHEMA.pop("$defs"),
    "properties": {
        "host": {"type": "string", "description": "SMTP 主机", "minLength": 1, "pattern": r"^\S+$"},
        "port": {"type": "integer", "description": "SMTP 端口", "minimum": 1, "maximum": 65535},
        "sender": _ADDRESS,
        "recipient": {**_ADDRESS, "x-logagent-workflow": True},
        "tls": {
            "type": "string",
            "description": "TLS 连接方式",
            "enum": ["none", "starttls", "implicit"],
            "default": "starttls",
        },
        "username": {
            "type": ["string", "null"],
            "description": "认证用户名",
            "minLength": 1,
            "default": None,
        },
        "password": {
            "description": "认证凭据引用",
            "anyOf": [_CREDENTIAL_SCHEMA, {"type": "null"}],
            "default": None,
            "x-logagent-credential": True,
        },
    },
    "required": ["host", "port", "sender", "recipient"],
    "allOf": [
        {
            "if": {"properties": {"username": {"type": "string"}}, "required": ["username"]},
            "then": {"required": ["password"], "properties": {"password": {"type": "object"}}},
            "else": {"properties": {"password": {"type": "null"}}},
        }
    ],
}


class EmailChannel:
    """One resident SMTP client per channel instance.

    A successful ``DATA`` response is the delivery boundary.  If the server
    has accepted the message and the response is lost, the exception is marked
    uncertain and the caller never retries implicitly.
    """

    def __init__(self, config: ChannelConfig, credentials: Any, *, client_factory=aiosmtplib.SMTP):
        validate_instance(config.options, resource_options_schema(_OPTIONS_SCHEMA), path=["options"])
        account, _ = split_options(config.options, _OPTIONS_SCHEMA)
        self._config = config.model_copy(update={"options": account}, deep=True)
        self._credentials = credentials
        self._client_factory = client_factory
        self._client = None
        self._send_lock = asyncio.Lock()
        self._stop_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._stop_task is not None:
            raise ChannelDeliveryError("email_closed", "邮件渠道已关闭")
        if self._client is not None:
            return
        options = self._config.options
        tls = options.get("tls", "starttls")
        self._client = self._client_factory(
            hostname=options["host"],
            port=options["port"],
            timeout=self._config.timeout,
            use_tls=tls == "implicit",
            start_tls=tls == "starttls",
            validate_certs=True,
        )

    def _message(self, notification: Notification, *, recipient: str, international: bool) -> bytes:
        options = self._config.options
        message = EmailMessage(policy=SMTPUTF8 if international else SMTP)
        message["From"], message["To"] = options["sender"], recipient
        message["Subject"] = notification.title
        identity = "\0".join((notification.session_id, notification.output_id, self._config.id))
        message["Message-ID"] = f"<{hashlib.sha256(identity.encode()).hexdigest()}@logagent.local>"
        message.set_content(notification.text.encode("utf-8"), maintype="text", subtype="plain", cte="base64")
        message.set_param("charset", "utf-8")
        return message.as_bytes()

    async def send(self, notification: Notification, *, options: dict) -> None:
        validate_workflow_options(options, _OPTIONS_SCHEMA)
        effective = {**self._config.options, **deepcopy(options)}
        validate_instance(effective, _OPTIONS_SCHEMA, path=["options"])
        recipient = effective["recipient"]
        stage = "prepare"
        owns_connection = False
        try:
            budget = remaining_delivery_time(self._config.timeout)
            async with asyncio.timeout(budget), self._send_lock:
                owns_connection = True
                if self._stop_task is not None or self._client is None:
                    raise ChannelDeliveryError("email_unavailable", "邮件渠道未就绪")
                client, account = self._client, self._config.options
                client.timeout = budget
                international = not (account["sender"] + recipient).isascii()
                body = self._message(notification, recipient=recipient, international=international)
                if not client.is_connected:
                    stage = "connect"
                    await client.connect()
                    await client.ehlo()
                    if account.get("username") is not None:
                        stage = "authenticate"
                        if self._credentials is None:
                            raise ChannelDeliveryError("credential_resolver_missing", "邮件凭据解析器未配置")
                        password = await self._credentials.resolve(account["password"])
                        if not isinstance(password, str) or not password:
                            raise ChannelDeliveryError("credential_invalid", "邮件凭据不可用")
                        await client.login(account["username"], password)
                if asyncio.current_task().cancelling():
                    raise asyncio.CancelledError
                if international and not client.supports_extension("smtputf8"):
                    raise ChannelDeliveryError("smtputf8_unavailable", "SMTP 不支持国际化邮箱地址")
                encoding = "utf-8" if international else "ascii"
                stage = "mail"
                await client.mail(account["sender"], options=["SMTPUTF8"] if international else [], encoding=encoding)
                stage = "recipient"
                await client.rcpt(recipient, encoding=encoding)
                stage = "data"
                await client.data(body)
        except asyncio.CancelledError:
            if owns_connection and self._client is not None:
                self._client.close()
            raise
        except Exception as exc:
            if owns_connection and self._client is not None:
                self._client.close()
            if isinstance(exc, ChannelDeliveryError):
                raise
            details = {"stage": stage, "exception_type": type(exc).__name__}
            response_error = isinstance(exc, aiosmtplib.errors.SMTPResponseException)
            if response_error:
                details["smtp_code"] = int(exc.code)
            raise ChannelDeliveryError(
                "email_delivery_failed",
                "SMTP 投递失败",
                uncertain=stage == "data" and not response_error,
                details=details,
            ) from exc

    async def stop(self) -> None:
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._close())
        await asyncio.shield(self._stop_task)

    async def _close(self) -> None:
        if self._client is None:
            return
        try:
            async with asyncio.timeout(_STOP_TIMEOUT), self._send_lock:
                if self._client.is_connected:
                    await self._client.quit()
        finally:
            self._client.close()


class EmailChannelType:
    name = "email"
    id_prefix = "email"
    description = "通过 SMTP 向单个收件人发送通知"
    capabilities = ["notification"]
    options_schema = _OPTIONS_SCHEMA

    async def create(self, config: ChannelConfig, credentials: Any) -> EmailChannel:
        return EmailChannel(config, credentials)
