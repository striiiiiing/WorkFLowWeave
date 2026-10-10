"""corespeed-io/wechatbot SDK, isolated in the lightweight Node bridge."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from workflowweave.channel.context import remaining_delivery_time
from workflowweave.channel.conversation import ChannelAddress, InboundHandler, InboundMessage
from workflowweave.channel.errors import ChannelDeliveryError
from workflowweave.models import ChannelConfig, Notification
from workflowweave.schema import (
    resource_options_schema,
    validate_instance,
    validate_workflow_options,
)

_LOGGER = logging.getLogger(__name__)
_STOP_TIMEOUT = 5.0
_BRIDGE = str(Path(__file__).with_name("bridge.mjs"))
_OPTIONS_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "account_id": {"type": "string", "minLength": 1, "pattern": r"^\S+$",
                       "title": "微信登录账号",
                       "description": "在网页扫码登录后自动填写 SDK 原始账号 ID；Token 自动保存到 state_dir/credentials.json，供后续使用。"},
        "state_dir": {"type": ["string", "null"], "default": None,
                      "description": "WeChatBot 登录与上下文状态目录。省略时为 ~/.wechatbot；例如 /var/lib/workflowweave/wechat/main。不同微信账号必须使用不同目录。"},
        "command": {"type": "string", "minLength": 1, "default": "node",
                    "description": "Node.js 可执行文件，例如 node 或 /usr/bin/node，要求 Node >=22；无需安装完整 OpenClaw。"},
        "target_id": {"type": "string", "minLength": 1, "pattern": r"^\S+$",
                      "description": "接收者的微信对端 ID，从入站消息获取；必须先由该用户发送消息建立上下文后才能回复。微信 iLink 平台限制：每条用户消息对应的 context_token 最多只能回复 10 条消息，达到上限后需再次发消息。因此不建议将微信作为单向通知渠道。", "x-workflowweave-workflow": True},
    },
    "required": ["account_id"],
}


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


class WechatOpenClawChannel:
    def __init__(self, config: ChannelConfig, credentials: Any = None, *, process_factory=None):
        del credentials  # The SDK owns QR login and persisted account tokens.
        validate_instance(config.options, resource_options_schema(_OPTIONS_SCHEMA), path=["options"])
        self._config = config.model_copy(deep=True)
        self._process_factory = process_factory or asyncio.create_subprocess_exec
        self._process = None
        self._reader_task = None
        self._stderr_task = None
        self._handler: InboundHandler | None = None
        self._ready = None
        self._pending: dict[str, asyncio.Future] = {}
        self._write_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()
        self._stop_task = None
        self._receiver_state = "stopped"
        self._receiver_error = None

    async def start(self) -> None:
        async with self._state_lock:
            if self._stop_task is not None:
                raise ChannelDeliveryError("wechat_openclaw_closed", "微信渠道已关闭")
            if self._process is not None:
                return
            options = self._config.options
            args = [_BRIDGE, "--account-id", options["account_id"]]
            if options.get("state_dir"):
                args.extend(["--state-dir", options["state_dir"]])
            self._ready = asyncio.get_running_loop().create_future()
            try:
                self._process = await self._process_factory(
                    options.get("command", "node"), *args,
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                self._reader_task = asyncio.create_task(self._read_stdout(), name="wechat-reader")
                self._stderr_task = asyncio.create_task(self._read_stderr(), name="wechat-stderr")
                async with asyncio.timeout(self._config.timeout):
                    await self._ready
            except ChannelDeliveryError:
                raise
            except Exception as exc:
                raise ChannelDeliveryError(
                    "wechat_openclaw_start_failed", "微信启动失败，请检查 Node >=22、WeChatBot 依赖及扫码登录",
                    details={"exception_type": type(exc).__name__},
                ) from exc

    async def _write(self, payload: dict, *, dispatched: asyncio.Event | None = None) -> None:
        process = self._process
        if (process is None or process.returncode is not None or process.stdin is None
                or (self._reader_task is not None and self._reader_task.done())):
            raise ChannelDeliveryError("wechat_openclaw_unavailable", "微信 bridge 未连接")
        async with self._write_lock:
            process.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
            if dispatched is not None:
                dispatched.set()  # drain may fail after Node received the send.
            await process.stdin.drain()

    async def _request(self, payload: dict) -> None:
        request_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        sending = payload["type"] == "send"
        dispatched = asyncio.Event()
        try:
            async with asyncio.timeout(remaining_delivery_time(self._config.timeout)):
                await self._write({**payload, "request_id": request_id}, dispatched=dispatched)
                await future
        except asyncio.CancelledError:
            raise
        except ChannelDeliveryError:
            raise
        except Exception as exc:
            raise ChannelDeliveryError(
                "wechat_openclaw_request_failed", "微信 bridge 请求失败",
                uncertain=sending and dispatched.is_set(),
                details={"exception_type": type(exc).__name__},
            ) from exc
        finally:
            self._pending.pop(request_id, None)
            if not future.done():
                future.cancel()

    async def send(self, notification: Notification, *, options: dict) -> None:
        validate_workflow_options(options, _OPTIONS_SCHEMA)
        effective = {**self._config.options, **options}
        validate_instance(effective, _OPTIONS_SCHEMA, path=["options"])
        target = effective.get("target_id")
        if not target:
            raise ChannelDeliveryError("wechat_openclaw_target_missing", "微信通知需要 target_id")
        await self._send_to(notification, target)

    async def reply(self, notification: Notification, *, address: ChannelAddress, options: dict) -> None:
        validate_workflow_options(options, _OPTIONS_SCHEMA)
        if address.kind != "weixin":
            raise ChannelDeliveryError("wechat_openclaw_address_invalid", "微信回复路由无效")
        await self._send_to(notification, address.target)

    async def _send_to(self, notification: Notification, target: str) -> None:
        if not notification.text.strip():
            raise ChannelDeliveryError("wechat_openclaw_message_empty", "微信消息不能为空")
        await self._request({"type": "send", "route": {"kind": "weixin", "target": target},
                             "text": notification.text,
                             "timeout_ms": max(1, int(remaining_delivery_time(self._config.timeout) * 1000))})

    async def start_receiving(self, handler: InboundHandler) -> None:
        if self._stop_task is not None:
            raise ChannelDeliveryError("wechat_openclaw_closed", "微信渠道已关闭")
        if self._handler is not None:
            raise ChannelDeliveryError("wechat_openclaw_already_receiving", "微信已在接收消息")
        self._handler = handler
        self._receiver_state = "connecting"
        try:
            await self._request({"type": "start_receiving"})
        except BaseException:
            self._handler = None
            self._receiver_state = "failed"
            raise
        self._receiver_state = "running"
        self._receiver_error = None

    async def stop_receiving(self) -> None:
        if self._handler is None:
            return
        await self._request({"type": "stop_receiving"})
        self._handler = None
        self._receiver_state = "stopped"

    def receiver_status(self) -> dict:
        return {"state": self._receiver_state, "error": self._receiver_error}

    async def _read_stdout(self) -> None:
        try:
            async for raw in self._process.stdout:
                event = json.loads(raw.decode("utf-8"))
                if not isinstance(event, dict):
                    raise ValueError("invalid bridge event")
                kind = event.get("type")
                if kind == "ready":
                    if event.get("protocol_version") != 1:
                        raise ValueError("unsupported bridge protocol")
                    if not self._ready.done():
                        self._ready.set_result(None)
                elif kind == "fatal":
                    raise ChannelDeliveryError("wechat_openclaw_bridge_failed", "微信 bridge 初始化或协议失败",
                                               details={"code": str(event.get("code", "unknown"))})
                elif kind == "receiver_error":
                    self._receiver_state = "failed"
                    self._receiver_error = str(event.get("code", "unknown"))
                    _LOGGER.error("wechat_receiver_failed", extra={"code": self._receiver_error})
                elif kind == "message":
                    await self._handle_inbound(event)
                elif kind in {"ack", "error"}:
                    pending = self._pending.get(event.get("request_id"))
                    if pending is None or pending.done():
                        continue  # A timed-out caller no longer owns this acknowledgement.
                    if kind == "error":
                        pending.set_exception(ChannelDeliveryError(
                            "wechat_openclaw_bridge_error", "微信 bridge 返回错误",
                            uncertain=event.get("uncertain") is True,
                            details={"code": str(event.get("code", "unknown"))},
                        ))
                    elif event.get("status") in {"sent", "accepted"}:
                        pending.set_result(None)
                    else:
                        raise ValueError("invalid acknowledgement")
                else:
                    raise ValueError("unknown bridge event")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail_pending(exc)
            _LOGGER.error("wechat_bridge_reader_failed", extra={"exception_type": type(exc).__name__})
        finally:
            self._fail_pending(ChannelDeliveryError(
                "wechat_openclaw_sidecar_stopped", "微信 bridge 连接已关闭", uncertain=True,
            ))

    def _fail_pending(self, error: Exception) -> None:
        if self._ready is not None and not self._ready.done():
            self._ready.set_exception(error)
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._receiver_state = "failed"
        self._receiver_error = type(error).__name__

    async def _handle_inbound(self, event: dict) -> None:
        fields = [event.get(key) for key in ("text", "message_id", "conversation_id", "sender_id")]
        if not all(_string(value) for value in fields) or event.get("conversation_kind") != "weixin":
            raise ValueError("invalid inbound message")
        text, message_id, target, sender = fields
        result = {"status": "not_receiving"}
        if self._handler is not None:
            inbound = InboundMessage(request_id=message_id, text=text, address=ChannelAddress(
                kind="weixin", target=target, sender=sender, message_id=message_id,
            ))
            result = await self._handler(inbound)
        await self._write({"type": "inbound_ack", "message_id": message_id, "status": result.get("status")})

    async def _read_stderr(self) -> None:
        async for raw in self._process.stderr:
            _LOGGER.debug("wechat_bridge_stderr", extra={"bytes": len(raw)})

    async def stop(self) -> None:
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._close(), name="wechat-close")
        await asyncio.shield(self._stop_task)

    async def _close(self) -> None:
        self._handler = None
        process = self._process
        if process is None:
            return
        if process.stdin is not None:
            process.stdin.close()
        if process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), _STOP_TIMEOUT)
            except TimeoutError:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), _STOP_TIMEOUT)
                except TimeoutError:
                    process.kill()
                    await process.wait()
        await asyncio.gather(*(task for task in (self._reader_task, self._stderr_task) if task),
                             return_exceptions=False)
        self._process = None
        self._receiver_state = "stopped"


class WechatOpenClawChannelType:
    name = "wechat_openclaw"
    id_prefix = "wechat_openclaw"
    description = "微信私信渠道：必须先由用户发送消息才能回复；每个 context_token 最多回复 10 条消息，因此不建议作为单向通知渠道"
    capabilities = ["notification", "conversation"]
    options_schema = _OPTIONS_SCHEMA

    async def create(self, config: ChannelConfig, credentials: Any) -> WechatOpenClawChannel:
        return WechatOpenClawChannel(config, credentials)

    async def start_login(self, options: dict):
        from .login import WechatLoginSession

        return WechatLoginSession(options)
