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

from workflowweave.channel.context import remaining_delivery_time
from workflowweave.channel.errors import ChannelDeliveryError
from workflowweave.models import ChannelConfig, Credential, Notification
from workflowweave.schema import (
    resource_options_schema,
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
        "host": {
            "type": "string", "title": "SMTP 服务器", "minLength": 1, "pattern": r"^\S+$",
            "description": "一般在邮箱设置的 POP3/IMAP/SMTP/Exchange/CardDAV 服务中获取 SMTP 信息。"
                           "服务器一般为 smtp.邮箱域名，具体以服务商说明为准；Gmail 示例：smtp.gmail.com。",
        },
        "port": {
            "type": "integer", "title": "SMTP 端口", "minimum": 1, "maximum": 65535,
            "description": "各邮箱的 SMTP 端口可能不同，请以服务商说明为准。"
                           "Gmail 示例：587（starttls），或 465（implicit）。",
        },
        "sender": {
            **_ADDRESS, "title": "发件人邮箱",
            "description": "邮件显示的发件人完整邮箱地址，通常与认证用户名一致；"
                           "其他地址需获邮箱服务商授权。Gmail 示例：yourname@gmail.com。",
        },
        "recipient": {
            **_ADDRESS, "title": "收件人邮箱", "x-workflowweave-workflow": True,
            "description": "实际接收通知的单个完整邮箱地址，可以与发件人相同，"
                           "也可在 Workflow 调用时覆盖。Gmail 示例：receiver@gmail.com。",
        },
        "tls": {
            "type": "string",
            "title": "TLS 连接方式",
            "description": "须与端口对应：starttls 为连接后升级加密，implicit 为直接加密，"
                           "none 为明文。Gmail 示例：端口 587 选 starttls，465 选 implicit。",
            "enum": ["none", "starttls", "implicit"],
            "default": "starttls",
        },
        "username": {
            "type": ["string", "null"],
            "title": "认证用户名",
            "description": "登录 SMTP 服务的账号，通常为完整发件人邮箱；填写时须同时提供授权码。"
                           "Gmail 示例：yourname@gmail.com。",
            "minLength": 1,
            "default": None,
        },
        "password": {
            "title": "授权码",
            "description": "填写邮箱服务生成的 SMTP 授权码，并同时填写认证用户名；保存时会加密。"
                           "不要填写邮箱登录密码。"
                           "Gmail 示例：开启两步验证后，在 Google 账号的“应用专用密码”中生成"
                           "16 位应用密码并去掉显示空格；该账号须支持应用专用密码。",
            "anyOf": [_CREDENTIAL_SCHEMA, {"type": "null"}],
            "default": None,
            "x-workflowweave-credential": True,
        },
    },
    "required": ["host", "port", "sender", "recipient"],
    "allOf": [
        {
            "if": {"properties": {"username": {"type": "string"}}, "required": ["username"]},
            "then": {"required": ["password"], "properties": {"password": {"type": "object"}}},
        },
        {
            "if": {"properties": {"password": {"type": "object"}}, "required": ["password"]},
            "then": {"required": ["username"], "properties": {"username": {"type": "string"}}},
        },
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
        # Keep workflow-marked defaults (recipient) on the account.  A call may
        # override them, but an omitted override must still use the configured
        # default recipient.
        self._config = config.model_copy(deep=True)
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
        message["Message-ID"] = f"<{hashlib.sha256(identity.encode()).hexdigest()}@workflowweave.local>"
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
    description = "通过 SMTP 向单个收件人发送通知；连接信息一般在邮箱设置的 POP3/IMAP/SMTP/Exchange/CardDAV 服务中获取"
    capabilities = ["notification"]
    options_schema = _OPTIONS_SCHEMA

    async def create(self, config: ChannelConfig, credentials: Any) -> EmailChannel:
        return EmailChannel(config, credentials)
