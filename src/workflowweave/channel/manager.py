from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from workflowweave.agent.commands import AgentCommand
from workflowweave.channel.agent import AgentChannelProcessor
from workflowweave.channel.base import BaseConversationChannel
from workflowweave.channel.bindings import ChannelBindings, InstanceBinding
from workflowweave.channel.context import delivery_deadline
from workflowweave.channel.conversation import ChannelAddress, InboundHandler, InboundMessage
from workflowweave.channel.errors import ChannelDeliveryError
from workflowweave.channel.unified_queue import QueueOutcome, UnifiedQueue
from workflowweave.errors import WorkFLowWeaveError, exception_error
from workflowweave.models import (
    CapabilityDescription,
    ChannelConfig,
    DeliveryResult,
    ErrorInfo,
    Notification,
)
from workflowweave.schema import split_options, validate_instance

_LOGGER = logging.getLogger(__name__)
_STOP_TIMEOUT = 5.0


class _BudgetExhausted(Exception):
    """A blocking plugin call overran the send budget before the loop could time out."""


@dataclass(eq=False)
class _Entry:
    """One resident instance keyed by the effective snapshot configuration."""

    key: tuple[str, str]
    channel: str
    owner: str
    instance: Any
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    stop_task: asyncio.Task[None] | None = None
    stopped: bool = False


@dataclass
class _ActiveSend:
    key: tuple[str, str]
    channel: str
    owner: str
    finished: asyncio.Event = field(default_factory=asyncio.Event)


@dataclass(frozen=True)
class _Admission:
    result: asyncio.Future
    duplicate: bool


class ChannelManager:
    def __init__(
        self,
        channel_register: Any,
        *,
        credentials: Any = None,
        stop_timeout: float = _STOP_TIMEOUT,
    ):
        if not math.isfinite(stop_timeout) or stop_timeout <= 0:
            raise ValueError("stop_timeout must be positive and finite")
        self._register = channel_register
        self._credentials = credentials
        self._entries: dict[tuple[str, str], _Entry] = {}
        self._retired: set[_Entry] = set()
        self._init_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._release_tasks: dict[tuple[str, str], asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()
        self._reload_lock = asyncio.Lock()
        self._stopping = False
        self._blocked_types: set[str] = set()
        self._unloaded_owners: set[str] = set()
        self._active_sends: dict[asyncio.Task[Any], _ActiveSend] = {}
        self._stop_task: asyncio.Task[None] | None = None
        self._stop_timeout = stop_timeout
        self._input_queue = UnifiedQueue()
        self._agent_processor: Any = None
        self._conversation_processor: Any = None
        self._conversation_base: BaseConversationChannel | None = None
        self.bindings: ChannelBindings | None = None
        self.configs: dict[str, ChannelConfig] = {}
        self._agent_configs: dict[str, ChannelConfig] = {}
        self.errors: dict[str, dict] = {}
        self._sync_lock = asyncio.Lock()
        self._sync_task: asyncio.Task[None] | None = None
        self._accepting = True
        self._suspended = False
        self._stop_generations: dict[tuple[str, str], int] = {}
        self._receiver_generations: dict[str, int] = {}
        self._pending_requests: dict[tuple[str, str, str], tuple[str, asyncio.Future]] = {}
        self._admission_lock = asyncio.Lock()
        self._web_channel = None

    def describe(self) -> list[CapabilityDescription]:
        return [x.model_copy(deep=True) for x in self._register.describe()]

    @property
    def active_operations(self) -> int:
        return self._input_queue.busy_count() + len(self._active_sends)

    @property
    def agent_channel(self):
        """Compatibility view of the injected Agent processing port."""
        return self._agent_processor

    @property
    def web_channel(self):
        if self._web_channel is None:
            from workflowweave.channel.web import WebChannel

            self._web_channel = WebChannel(self)
        return self._web_channel

    async def configure_agent(self, processor: Any, bindings_path) -> None:
        """Attach the Agent processing port and durable channel binding store."""
        from workflowweave.channel.web import WebChannel

        self._agent_processor = processor
        self._conversation_base = BaseConversationChannel(processor)
        self._web_channel = WebChannel(self)
        self.bindings = ChannelBindings(bindings_path)
        self._conversation_processor = AgentChannelProcessor(processor, self.bindings)

    async def start_agent(self, configs) -> None:
        if self.bindings is None:
            raise WorkFLowWeaveError("not_ready", "Agent 渠道处理端口尚未装配")
        await self.bindings.start()
        configs = list(configs)
        for config in configs:
            session_id = self.bindings.instance(config.id).session_id
            if session_id is not None:
                await self._agent_processor.get_session(session_id)
        await self._reconcile_agent_operations()
        await self.configure(configs)

    async def _reconcile_agent_operations(self) -> None:
        for peer, request, operation_id, channel_id, operation in await self.bindings.recovery_candidates():
            evidence = await self._agent_processor.recover_request(
                operation_id, channel=channel_id, operation=operation,
            )
            if evidence is None:
                continue
            response, status = evidence
            await self.bindings.complete(
                peer, request, response,
                status="interrupted" if status == "cancelled" else status,
                delivery={"status": "outcome_unknown", "error": {
                    "code": "delivery_interrupted",
                    "message": "重启前的渠道投递没有确认结果，不自动重发",
                }},
            )

    def request_sync(self, configs) -> None:
        previous = self._sync_task

        async def sync():
            if previous is not None:
                await asyncio.gather(previous, return_exceptions=True)
            await self.configure(configs)

        self._sync_task = asyncio.create_task(sync(), name="channel:configure")
        self._sync_task.add_done_callback(self._configuration_done)

    def _configuration_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            self.errors["configuration"] = {
                "code": getattr(error, "code", "channel_configuration_failed"),
                "exception_type": type(error).__name__,
            }
            _LOGGER.error("channel_configuration_failed", exc_info=error)

    async def configure(self, configs) -> None:
        configs = list(configs)
        self._agent_configs = {config.id: config.model_copy(deep=True) for config in configs}
        desired = {config.id: config.model_copy(deep=True) for config in configs
                   if config.enabled and config.agent_enabled}
        async with self._sync_lock:
            if not self._accepting or self._suspended:
                return
            for ident, old in list(self.configs.items()):
                if desired.get(ident) != old:
                    self._receiver_generations[ident] = self._receiver_generations.get(ident, 0) + 1
                    await self.stop_receiving(old)
                    del self.configs[ident]
            for ident, config in desired.items():
                if ident in self.configs:
                    continue
                generation = self._receiver_generations.get(ident, 0) + 1
                self._receiver_generations[ident] = generation
                self.configs[ident] = config
                try:
                    await self.start_receiving(
                        config, lambda message, bound=config, version=generation: self.enqueue(
                            bound.id, message, expected=bound, generation=version,
                        ),
                    )
                except BaseException:
                    self._receiver_generations[ident] += 1
                    del self.configs[ident]
                    raise
            self.errors.pop("configuration", None)

    def _conversation_config(self, channel_id: str, config=None) -> ChannelConfig:
        if self.bindings is None or self.bindings._db is None:
            raise WorkFLowWeaveError("not_ready", "Agent 渠道处理端口尚未装配")
        config = config or self._agent_configs.get(channel_id)
        if config is None or config.id != channel_id:
            raise WorkFLowWeaveError("channel_not_found", "渠道实例不存在")
        channel = self._register.get(config.channel)
        if channel is None or "conversation" not in channel.capabilities:
            raise WorkFLowWeaveError("channel_not_conversation", "渠道不支持双向对话")
        return config

    async def conversation(self, channel_id: str, *, config=None) -> dict:
        self._conversation_config(channel_id, config)
        return {"session_id": self.bindings.instance(channel_id).session_id}

    async def bind_conversation(self, channel_id: str, session_id: str | None, *,
                                config=None) -> dict:
        self._conversation_config(channel_id, config)
        binding = await self._conversation_processor.bind(channel_id, session_id)
        return {"session_id": binding.session_id}

    @staticmethod
    def _digest(value: Any) -> str:
        encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(encoded.encode()).hexdigest()

    @classmethod
    def _peer(cls, config: ChannelConfig, message: InboundMessage) -> str:
        account = config.options.get("app_id") if config.channel == "qq" else None
        return cls._digest([config.id, account, message.address.peer])

    async def _migrate_legacy_peer(self, config, message):
        peer = self._peer(config, message)
        legacy_peer = self._digest([
            config.id, config.channel, config.options, message.address.peer,
        ])
        await self.bindings.migrate_peer(legacy_peer, peer)
        return peer

    @classmethod
    def _agent_request_id(cls, channel: str, peer: str, request: str) -> str:
        return f"channel:{cls._digest([channel, peer, request])}"

    async def _interrupt_request(self, payload):
        error = WorkFLowWeaveError("message_interrupted", "渠道输入在处理前已中断")
        if "command" in payload:
            command = payload["command"]
            peer = (f"web:session:{command.session}" if command.session else
                            f"web:create:{command.request_id}")
            await self.bindings.complete(peer, command.request_id, {
                "kind": "error", "error": error.info.model_dump(),
            })
            await self.bindings.delivered(peer, command.request_id, {"status": "not_started"})
            return error
        message = payload["message"]
        config = payload["config"]
        peer = payload["peer"]
        response = {"channel": config.id, "kind": "error", "error": error.info.model_dump()}
        await self.bindings.complete(peer, message.request_id, response)
        await self.bindings.delivered(peer, message.request_id, {"status": "not_started"})
        return response

    async def _admit_request(self, key, identity, digest, payload, handler, *, switch=False,
                             stop=False) -> _Admission:
        if self.bindings is None:
            raise WorkFLowWeaveError("not_ready", "Agent 渠道处理端口尚未装配")
        peer, request = identity
        pending_key = (key[0], peer, request)
        async with self._admission_lock:
            pending = self._pending_requests.get(pending_key)
            if pending is not None:
                if pending[0] != digest:
                    raise WorkFLowWeaveError("request_conflict", "渠道消息 ID 对应了不同内容")
                future = pending[1]
                duplicate = True
            else:
                previous = await self.bindings.lookup(peer, request, digest)
                if previous is not None:
                    future = asyncio.get_running_loop().create_future()
                    future.set_result({**previous, "deduplicated": True})
                    return _Admission(future, True)
                duplicate = False
                generation_key = key[:2]

                async def reserve():
                    await self.bindings.claim(
                        peer, request, digest,
                        operation_id=self._agent_request_id(
                            payload["config"].id if "config" in payload else "web", peer, request,
                        ),
                        channel_id=payload["config"].id if "config" in payload else "web",
                        operation=payload["operation"],
                    )
                    if stop:
                        self._stop_generations[generation_key] = (
                            self._stop_generations.get(generation_key, 0) + 1
                        )
                    payload["generation"] = self._stop_generations.get(generation_key, 0)

                async def interrupt(older):
                    return await self._interrupt_request(older)

                try:
                    future = await self._input_queue.admit(
                        key, payload, handler, switch=switch, on_admit=reserve,
                        on_interrupt=interrupt if stop else None,
                    )
                except RuntimeError as exc:
                    raise self._queue_error(str(exc)) from exc
                except BaseException:
                    if stop:
                        await self.bindings.complete(peer, request, {
                            "kind": "error", "error": WorkFLowWeaveError(
                                "channel_admission_failed", "停止请求受理失败"
                            ).info.model_dump(),
                        })
                    raise
                self._pending_requests[pending_key] = (digest, future)

                def done(_):
                    self._pending_requests.pop(pending_key, None)
                    if not future.cancelled():
                        future.exception()

                future.add_done_callback(done)
        return _Admission(future, duplicate)

    @staticmethod
    def _queue_error(code: str) -> WorkFLowWeaveError:
        messages = {
            "channel_queue_full": "渠道输入队列已满",
            "channel_manager_stopping": "渠道网关正在关闭",
            "channel_manager_suspended": "渠道正在重载，消息未受理",
        }
        return WorkFLowWeaveError(code, messages.get(code, "渠道输入队列不可用"))

    async def enqueue(self, channel_id: str, inbound: InboundMessage, *, expected=None,
                      generation=None):
        """Admit transport input and let the keyed consumer call the Agent port."""
        if self._conversation_processor is None:
            raise WorkFLowWeaveError("not_ready", "Agent 渠道处理端口尚未装配")
        message = InboundMessage.model_validate(inbound).model_copy(deep=True)
        config = self.configs.get(channel_id)
        if not self._accepting or self._suspended or config is None or (
            expected is not None and config != expected
        ) or (generation is not None and generation != self._receiver_generations.get(channel_id)):
            raise WorkFLowWeaveError("channel_disabled", "渠道未启用 Agent 接收")
        command = AgentCommand(channel=channel_id, request_id=message.request_id, text=message.text)
        try:
            operation, _ = command.operation()
        except WorkFLowWeaveError:
            operation = "invalid"
        priority = "stop" if operation == "stop" else (
            "normal" if operation in {"message", "invalid"} else "command"
        )
        peer = await self._migrate_legacy_peer(config, message)
        admitted = await self._admit_request(
            ("channel", config.id, priority), (peer, message.request_id),
            self._digest(message.model_dump(mode="json")),
            {"config": config, "message": message, "peer": peer, "operation": operation,
             "binding": self.bindings.instance(config.id)},
            self._consume_inbound,
            switch=operation in {"new", "resume", "fork", "workflow"},
            stop=operation == "stop",
        )
        return {"status": "duplicate" if admitted.duplicate else "accepted"}

    async def _consume_inbound(self, value) -> QueueOutcome:
        config, message, peer, operation = (
            value[name] for name in ("config", "message", "peer", "operation")
        )
        command = AgentCommand(
            channel=config.id,
            request_id=self._agent_request_id(config.id, peer, message.request_id),
            text=message.text,
        )
        binding = value["binding"]
        def valid():
            return value["generation"] == self._stop_generations.get(("channel", config.id), 0)
        try:
            if operation != "stop" and not valid():
                raise WorkFLowWeaveError("message_interrupted", "消息因更高优先级的停止命令而取消")
            await self.bindings.processing(peer, message.request_id)
            processed = (await self._conversation_processor.stop(
                config.id, command, binding=binding,
            )
                        if operation == "stop" else
                        await self._conversation_processor.process(
                            config.id, command, binding=binding, valid=valid,
                        ))
            response, binding = processed.response, processed.binding
        except WorkFLowWeaveError as exc:
            response = {"channel": config.id, "kind": "error", "error": exc.info.model_dump()}
        result = response.get("result", {})
        has_turn = response["kind"] == "turn" and isinstance(result, dict) and result.get("turn_id")
        queued_command = response["kind"] == "turn" and result.get("status") == "queued"
        await self.bindings.complete(
            peer, message.request_id, response,
            status="processing" if has_turn or queued_command else None,
        )
        if queued_command:
            settle = self._finish_command(config, message, peer, command, response, binding)
        elif has_turn and operation in {"message", "append", "compact"}:
            settle = self._finish_inbound(config, message, peer, response["result"], binding)
        else:
            text = (f"{response['error']['code']}: {response['error']['message']}"
                    if response["kind"] == "error" else self._command_text(response))
            settle = self._reply_inbound(
                config, message, peer, binding.session_id or "channel_command", text, binding,
            )
        return QueueOutcome(response, settle)

    @staticmethod
    def _command_text(response):
        result = response["result"]
        if response["kind"] == "session":
            return f"会话 {result['session_id']}（{result.get('status', 'created')}）"
        return json.dumps(result, ensure_ascii=False, default=str)

    async def _finish_inbound(self, config, message, peer, accepted, binding):
        result = await self._conversation_base.finish_turn(accepted["turn_id"])
        await self.bindings.set_status(peer, message.request_id, result.status)
        await self._reply_inbound(config, message, peer, accepted["session_id"], result.text, binding)

    async def _finish_command(self, config, message, peer, command, response, binding):
        result = response["result"]
        outcome = await self._conversation_base.finish_command(
            result["session_id"],
            request_id=command.request_id if response["kind"] == "turn"
            and result.get("turn_id") else None,
            event_id=result["event_id"] if not result.get("turn_id") else None,
        )
        await self.bindings.set_status(peer, message.request_id, outcome.status)
        await self._reply_inbound(config, message, peer, result["session_id"], outcome.text, binding)

    async def _reply_inbound(self, config, message, peer, session, text, binding):
        outcome = await self.bindings.outcome(peer, message.request_id)
        result = outcome["response"].get("result") if outcome["response"] else None
        receipt = await self.send(
            config, Notification(
                session_id=session, output_id="agent_reply", text=text,
                metadata={"request_id": message.request_id,
                          "turn_id": result.get("turn_id") if isinstance(result, dict) else None},
            ),
            reply_to=message.address,
            binding=binding,
        )
        await self.bindings.delivered(peer, message.request_id, receipt.model_dump(mode="json"))
        if receipt.status != "success":
            raise WorkFLowWeaveError("channel_reply_failed", "Agent 回复未送达", receipt.model_dump(mode="json"))

    async def dispatch_web(self, command):
        """Project the existing Web command contract onto the same queue."""
        if self._agent_processor is None:
            raise WorkFLowWeaveError("not_ready", "Agent 渠道处理端口尚未装配")
        operation, _ = command.operation()
        if command.channel != "web":
            raise WorkFLowWeaveError("invalid_argument", "Web 请求不能指定其他渠道")
        priority = "stop" if operation == "stop" else (
            "normal" if operation == "message" else "command"
        )
        peer = f"web:session:{command.session}" if command.session else f"web:create:{command.request_id}"
        key = ("web", peer, priority)

        async def consume(envelope):
            envelope = envelope["command"]
            def valid():
                return payload["generation"] == self._stop_generations.get(key[:2], 0)

            await self.bindings.processing(peer, envelope.request_id)
            try:
                if operation != "stop" and not valid():
                    raise WorkFLowWeaveError("message_interrupted", "消息因更高优先级的停止命令而取消")
                agent_command = envelope.model_copy(update={"request_id": self._agent_request_id(
                    "web", peer, envelope.request_id,
                )})
                response = (await self._conversation_processor.stop_web(peer, agent_command)
                            if operation == "stop" else
                            await self._conversation_processor.dispatch_web(
                                peer, agent_command, valid=valid,
                            ))
            except WorkFLowWeaveError as exc:
                await self.bindings.complete(peer, envelope.request_id, {
                    "kind": "error", "error": exc.info.model_dump(),
                }, delivery={"status": "not_started"})
                raise
            result = response.get("result", {})
            has_turn = response["kind"] == "turn" and isinstance(result, dict) and result.get("turn_id")
            queued_command = response["kind"] == "turn" and result.get("status") == "queued"
            await self.bindings.complete(
                peer, envelope.request_id, response,
                status="processing" if has_turn or queued_command else None,
                delivery={"status": "not_started"},
            )
            settle = None
            if queued_command:
                settle = self._finish_web_command(peer, envelope, agent_command, response)
            elif has_turn and operation in {"message", "append", "compact"}:
                settle = self._finish_web_turn(peer, envelope.request_id, result["turn_id"])
            return QueueOutcome(response, settle)

        payload = {"command": command.model_copy(deep=True), "operation": operation}
        admission = await self._admit_request(
            key, (peer, command.request_id), self._digest(command.model_dump(mode="json")),
            payload, consume, switch=operation in {"new", "resume", "fork", "workflow"},
            stop=operation == "stop",
        )
        result = await asyncio.shield(admission.result)
        return {**result, "deduplicated": True} if admission.duplicate else result

    async def _finish_web_turn(self, peer, request_id, turn_id):
        outcome = await self._conversation_base.finish_turn(turn_id)
        await self.bindings.set_status(peer, request_id, outcome.status)

    async def _finish_web_command(self, peer, envelope, agent_command, response):
        result = response["result"]
        outcome = await self._conversation_base.finish_command(
            result["session_id"],
            request_id=agent_command.request_id if result.get("turn_id") else None,
            event_id=result["event_id"] if not result.get("turn_id") else None,
        )
        await self.bindings.set_status(peer, envelope.request_id, outcome.status)

    async def outcome(self, config, message):
        if self.bindings is None:
            raise WorkFLowWeaveError("not_ready", "Agent 渠道处理端口尚未装配")
        peer = await self._migrate_legacy_peer(config, message)
        return await self.bindings.outcome(peer, message.request_id)

    async def web_outcome(self, request_id: str, *, session: str | None = None):
        if self.bindings is None:
            raise WorkFLowWeaveError("not_ready", "Agent 渠道处理端口尚未装配")
        peer = f"web:session:{session}" if session else f"web:create:{request_id}"
        return await self.bindings.outcome(peer, request_id)

    async def suspend(self):
        await self._input_queue.suspend(
            cancel_pending=True, on_interrupt=self._interrupt_request if self.bindings else None,
        )
        self._suspended = True
        async with self._sync_lock:
            for config in list(self.configs.values()):
                self._receiver_generations[config.id] = (
                    self._receiver_generations.get(config.id, 0) + 1
                )
                await self.stop_receiving(config)
                self.configs.pop(config.id)

    async def resume(self, configs):
        await self._input_queue.resume()
        self._suspended = False
        await self.configure(configs)

    async def close_agent(self):
        self._accepting = False
        if self._sync_task is not None:
            await asyncio.gather(self._sync_task, return_exceptions=True)
        await self.suspend()
        unfinished = await self._input_queue.drain(self._stop_timeout)
        if unfinished:
            _LOGGER.warning("channel_reply_drain_timeout", extra={
                "event": "channel_reply_drain_timeout", "active_consumers": unfinished,
            })
        await self._input_queue.close()
        if self.bindings is not None:
            await self.bindings.close()

    async def close(self):
        """Close Agent ingress, bindings and queue consumers."""
        await self.close_agent()

    def validate(self, config: ChannelConfig) -> None:
        if config.id == "web":
            raise WorkFLowWeaveError("invalid_config", "web 是内置 Agent 渠道的保留实例 ID")
        channel = self._register.get(config.channel)
        if channel is None:
            raise ValueError("channel_missing")
        if "notification" not in channel.capabilities:
            raise ValueError("channel_not_notification")
        if config.agent_enabled and "conversation" not in channel.capabilities:
            raise WorkFLowWeaveError("invalid_config", "此渠道不支持 Agent 双向交互")
        validate_instance(config.options, channel.options_schema, path=["options"])

    def _instance_config(self, config: ChannelConfig) -> ChannelConfig:
        channel = self._register.get(config.channel)
        if channel is None:
            raise WorkFLowWeaveError("channel_missing", "通知渠道未注册")
        instance_options, _ = split_options(config.options, channel.options_schema)
        return config.model_copy(update={"options": instance_options}, deep=True)

    def _key(self, config: ChannelConfig) -> tuple[str, str]:
        # Invocation-only fields do not change the resident target. In particular,
        # different send budgets must still join the same one-time initialization.
        effective = self._instance_config(config).model_dump(
            mode="json", exclude={"enabled", "timeout", "agent_enabled"},
        )
        return (
            config.id,
            json.dumps(effective, sort_keys=True, separators=(",", ":")),
        )

    @staticmethod
    def _receipt(
        config: ChannelConfig,
        notification: Notification,
        *,
        status: str,
        attempts: int,
        error: ErrorInfo | None = None,
    ) -> DeliveryResult:
        if error is not None:
            _LOGGER.warning(
                "notification_failed",
                extra={
                    "event": "notification_failed", "session_id": notification.session_id,
                    "channel_id": config.id, "output_id": notification.output_id,
                    "error_code": error.code, "delivery_status": status,
                    "delivery_uncertain": bool(error.details.get("delivery_uncertain")),
                },
            )
        return DeliveryResult(
            channel_id=config.id,
            output_id=notification.output_id,
            status=status,
            attempts=attempts,
            error=error,
        )

    def _admit(self) -> None:
        if self._stopping:
            raise WorkFLowWeaveError("channel_manager_stopping", "渠道网关正在关闭")

    def _channel_owner(self, channel: str) -> str:
        for description in self._register.describe():
            if description.name == channel:
                return description.plugin
        return ""

    async def _entry(
        self,
        key: tuple[str, str],
        channel: Any,
        config: ChannelConfig,
        *,
        deadline: float,
    ) -> _Entry:
        """Return the resident instance, starting it once for concurrent first use."""
        async with self._lock:
            init_lock = self._init_locks.setdefault(key, asyncio.Lock())
        async with init_lock:
            async with self._lock:
                self._admit()
                entry = self._entries.get(key)
                if entry is not None:
                    if entry.stop_task is not None:
                        raise WorkFLowWeaveError("channel_unavailable", "渠道尚未完成关闭")
                    return entry
            instance = None
            try:
                instance = await channel.create(self._instance_config(config), self._credentials)
                if asyncio.get_running_loop().time() >= deadline:
                    raise _BudgetExhausted
                await instance.start()
                if asyncio.get_running_loop().time() >= deadline:
                    raise _BudgetExhausted
                async with self._lock:
                    self._admit()
                    entry = _Entry(key, config.channel, self._channel_owner(config.channel), instance)
                    self._entries[key] = entry
                    return entry
            except BaseException as initialization_error:
                try:
                    await self._cleanup_initialization(instance, config, key)
                except asyncio.CancelledError:
                    raise
                except BaseException as cleanup_error:
                    raise self._initialization_cleanup_error(
                        initialization_error, cleanup_error
                    ) from initialization_error
                raise

    async def _cleanup_initialization(self, instance, config, key) -> None:
        if instance is None:
            return
        entry = _Entry(key, config.channel, self._channel_owner(config.channel), instance)
        self._retired.add(entry)
        await self._stop_entry(entry)

    @staticmethod
    def _exception_summary(exc: BaseException) -> dict[str, Any]:
        return {
            "code": "channel_cleanup_failed",
            "message": "渠道清理发生异常",
            "details": {"exception_type": type(exc).__name__},
        }

    @classmethod
    def _initialization_cleanup_error(
        cls, initialization_error: BaseException, cleanup_error: BaseException
    ) -> WorkFLowWeaveError:
        return WorkFLowWeaveError(
            "channel_initialization_cleanup_failed",
            "通知渠道初始化失败且清理失败",
            {
                "initialization_error": cls._exception_summary(initialization_error),
                "cleanup_error": cls._exception_summary(cleanup_error),
            },
        )

    async def _begin_send(self, config: ChannelConfig) -> tuple[str, str]:
        while True:
            async with self._lock:
                self._admit()
                owner = self._channel_owner(config.channel)
                if (
                    config.channel in self._blocked_types
                    or owner in self._unloaded_owners
                ):
                    raise WorkFLowWeaveError("channel_unavailable", "渠道正在卸载或替换")
                key = self._key(config)
                release_task = self._release_tasks.get(key)
                if release_task is None:
                    task = asyncio.current_task()
                    if task is None:
                        raise RuntimeError("ChannelManager.send requires an asyncio task")
                    self._active_sends[task] = _ActiveSend(key, config.channel, owner)
                    return key
            await asyncio.wait([release_task])

    def _end_send(self) -> None:
        active = self._active_sends.pop(asyncio.current_task())
        active.finished.set()

    async def start_receiving(self, config: ChannelConfig, handler: InboundHandler) -> None:
        """Attach an Agent receiver to the same resident instance used by send."""
        if not config.enabled or not config.agent_enabled:
            raise WorkFLowWeaveError("channel_disabled", "渠道未启用 Agent 接收")
        key = None
        async with asyncio.timeout(config.timeout):
            try:
                key = await self._begin_send(config)
                self.validate(config)
                entry = await self._entry(
                    key, self._register.get(config.channel), config,
                    deadline=asyncio.get_running_loop().time() + config.timeout,
                )
                await entry.instance.start_receiving(handler)
            finally:
                if key is not None:
                    self._end_send()

    async def stop_receiving(self, config: ChannelConfig) -> None:
        entry = self._entries.get(self._key(config))
        if entry is not None:
            async with asyncio.timeout(self._stop_timeout):
                await entry.instance.stop_receiving()

    def receiver(self, config: ChannelConfig):
        """Return a running receiver for transport-specific local diagnostics."""
        entry = self._entries.get(self._key(config))
        if entry is None:
            raise WorkFLowWeaveError("channel_unavailable", "渠道接收实例尚未启动")
        return entry.instance

    async def send(self, config: ChannelConfig, notification: Notification, *,
                   reply_to: ChannelAddress | None = None,
                   binding: InstanceBinding | None = None) -> DeliveryResult:
        config, notification = deepcopy(config), deepcopy(notification)
        if not config.enabled:
            return self._receipt(config, notification, status="skipped", attempts=0)
        channel = self._register.get(config.channel)
        if channel is None:
            return self._receipt(
                config,
                notification,
                status="failed",
                attempts=0,
                error=ErrorInfo(code="channel_missing", message="通知渠道未注册"),
            )
        # One budget covers lock waits, instance creation, start and the single send.
        entered = False
        preparing = True
        key: tuple[str, str] | None = None
        deadline = asyncio.get_running_loop().time() + config.timeout
        timeout = asyncio.timeout(config.timeout)
        try:
            async with timeout:
                key = await self._begin_send(config)
                self.validate(config)
                channel = self._register.get(config.channel)
                entry = await self._entry(key, channel, config, deadline=deadline)
                preparing = False
                async with entry.send_lock:
                    if binding is not None and (
                        self.bindings.instance(config.id) != binding
                        or self._agent_configs.get(config.id) != config
                    ):
                        return self._receipt(
                            config, notification, status="failed", attempts=0,
                            error=ErrorInfo(
                                code="channel_binding_changed",
                                message="渠道绑定或接收配置已变更，旧输出未发送",
                            ),
                        )
                    if reply_to is not None and "conversation" not in channel.capabilities:
                        raise WorkFLowWeaveError("channel_not_conversation", "渠道不支持回复")
                    if asyncio.get_running_loop().time() >= deadline:
                        raise _BudgetExhausted
                    if asyncio.current_task().cancelling():
                        raise asyncio.CancelledError
                    _, options = split_options(config.options, channel.options_schema)
                    entered = True
                    budget_token = delivery_deadline.set(deadline)
                    try:
                        if reply_to is None:
                            await entry.instance.send(notification, options=options)
                        else:
                            await entry.instance.reply(
                                notification, address=reply_to.model_copy(deep=True), options=options,
                            )
                    finally:
                        delivery_deadline.reset(budget_token)
                    if asyncio.current_task().cancelling():
                        raise asyncio.CancelledError
            return self._receipt(config, notification, status="success", attempts=1)
        except Exception as exc:
            status = "failed"
            if isinstance(exc, _BudgetExhausted) or (
                isinstance(exc, TimeoutError) and timeout.expired()
            ):
                status = "timeout"
                error = ErrorInfo(
                    code="delivery_timeout",
                    message="通知发送超出总时限",
                    details={"delivery_uncertain": entered},
                )
            elif isinstance(exc, ChannelDeliveryError):
                error = ErrorInfo(
                    code=exc.code,
                    message=exc.info.message,
                    details={**exc.details, "delivery_uncertain": entered and exc.uncertain},
                )
            else:
                details = {"delivery_uncertain": entered}
                if isinstance(exc, WorkFLowWeaveError):
                    details.update(exc.info.details)
                error = exception_error(
                    exc,
                    code="channel_prepare_failed" if preparing else "delivery_failed",
                    message="通知渠道准备失败" if preparing else "通知发送失败",
                    details=details,
                )
            return self._receipt(
                config, notification, status=status, attempts=int(entered), error=error,
            )
        finally:
            if key is not None:
                self._end_send()

    async def _stop_entry(self, entry: _Entry) -> None:
        if entry.stopped:
            return
        if entry.stop_task is None:
            entry.stop_task = asyncio.create_task(entry.instance.stop())
        try:
            await asyncio.wait_for(asyncio.shield(entry.stop_task), self._stop_timeout)
        except TimeoutError as exc:
            raise WorkFLowWeaveError("channel_stop_timeout", "渠道关闭尚未完成") from exc
        entry.stopped = True
        async with self._lock:
            self._retired.discard(entry)
            if self._entries.get(entry.key) is entry:
                self._entries.pop(entry.key)
                self._init_locks.pop(entry.key, None)

    async def _wait_for_sends(self, key: tuple[str, str] | None = None) -> None:
        async with self._lock:
            pending = [active.finished.wait() for active in self._active_sends.values()
                       if key is None or active.key == key]
        await asyncio.wait_for(asyncio.gather(*pending), self._stop_timeout)

    async def _drain_and_stop(self, keys: set[tuple[str, str]]) -> None:
        for key in keys:
            try:
                await self._wait_for_sends(key)
            except TimeoutError as exc:
                raise WorkFLowWeaveError(
                    "channel_release_timeout",
                    "渠道发送未在清理预算内结束",
                    {"channel_id": key[0], "timeout": self._stop_timeout},
                ) from exc

        async with self._lock:
            entries = [self._entries[key] for key in keys if key in self._entries]
        errors: list[BaseException] = []
        for entry in entries:
            try:
                await self._stop_entry(entry)
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise WorkFLowWeaveError(
                "channel_release_failed",
                "通知渠道实例释放失败",
                {"errors": [self._exception_summary(exc) for exc in errors]},
            )

    async def release(self, config: ChannelConfig) -> None:
        """Release one snapshot instance after its current sends finish."""
        key = self._key(config)
        async with self._lock:
            self._admit()
            task = self._release_tasks.get(key)
            if task is None:
                task = asyncio.create_task(self._release_once(key))
                self._release_tasks[key] = task
        await asyncio.shield(task)

    async def _release_once(self, key: tuple[str, str]) -> None:
        try:
            await self._wait_for_sends(key)
            async with self._lock:
                entry = self._entries.get(key)
            if entry is not None:
                await self._stop_entry(entry)
        finally:
            async with self._lock:
                self._release_tasks.pop(key, None)

    async def unload_owner(self, owner: str) -> None:
        """Close admission for the owner before draining its resident instances."""
        async with self._reload_lock:
            async with self._lock:
                self._admit()
                owned_types = {
                    item.name for item in self._register.describe() if item.plugin == owner
                }
                if self._input_queue.busy_count(channel_types=owned_types):
                    raise WorkFLowWeaveError("plugin_reload_conflict", "渠道仍有活动对话，不能卸载插件")
                self._unloaded_owners.add(owner)
                keys = {
                    entry.key for entry in self._entries.values() if entry.owner == owner
                } | {
                    active.key for active in self._active_sends.values() if active.owner == owner
                }
            await self._drain_and_stop(keys)

    async def replace_register(self, channel_register: Any) -> None:
        """Replace changed implementations, including registrations with the same name."""
        async with self._reload_lock:
            async with self._lock:
                self._admit()
                old_names = {item.name for item in self._register.describe()} | {
                    entry.channel for entry in self._entries.values()
                }
                new_owners = {item.name: item.plugin for item in channel_register.describe()}
                changed = set()
                for name in old_names:
                    old, new = self._register.get(name), channel_register.get(name)
                    if (
                        old is None or new is None or old.create != new.create
                        or old.options_schema != new.options_schema
                        or old.capabilities != new.capabilities
                        or self._channel_owner(name) != new_owners.get(name)
                        or self._channel_owner(name) in self._unloaded_owners
                    ):
                        changed.add(name)
                if self._input_queue.busy_count(channel_types=changed):
                    raise WorkFLowWeaveError("plugin_reload_conflict", "渠道仍有活动对话，不能替换插件")
                self._blocked_types.update(changed)
                keys = {
                    entry.key for entry in self._entries.values() if entry.channel in changed
                } | {
                    active.key for active in self._active_sends.values() if active.channel in changed
                }
            # On failure retain old registrations and blocked admission; callers
            # can retry cleanup without losing ownership of unfinished instances.
            await self._drain_and_stop(keys)
            async with self._lock:
                self._register = channel_register
                self._blocked_types.difference_update(changed)
                self._unloaded_owners.difference_update(
                    item.plugin for item in channel_register.describe()
                )

    async def reload_register(self, channel_register: Any) -> None:
        """Lifecycle-facing alias for replacing the readonly registry view."""
        await self.replace_register(channel_register)

    async def stop(self) -> None:
        if self.bindings is not None and self.bindings._db is not None:
            await self.suspend()
        await self._input_queue.close()
        async with self._lock:
            if self._stop_task is None or (
                self._stop_task.done() and (self._entries or self._retired or self._active_sends)
            ):
                self._stopping = True
                self._stop_task = asyncio.create_task(self._stop_entries())
            stop_task = self._stop_task
        await asyncio.shield(stop_task)

    async def _stop_entries(self) -> None:
        try:
            await self._wait_for_sends()
        except TimeoutError:
            # Drain first; after the budget expires cancellation prevents new
            # external operations and lets send finally blocks release ownership.
            for task in tuple(self._active_sends):
                task.cancel()
            try:
                await self._wait_for_sends()
            except TimeoutError as exc:
                raise WorkFLowWeaveError(
                    "channel_stop_failed", "活动渠道调用未响应取消",
                    {"active_sends": len(self._active_sends)},
                ) from exc
        async with self._lock:
            entries = [*self._entries.values(), *self._retired]
            releases = list(self._release_tasks.values())
        results = await asyncio.gather(
            *(self._stop_entry(entry) for entry in entries),
            *releases, return_exceptions=True,
        )
        errors = [result for result in results if isinstance(result, BaseException)]
        if errors:
            raise WorkFLowWeaveError(
                "channel_stop_failed", "通知渠道实例关闭失败",
                {"errors": [self._exception_summary(exc) for exc in errors]},
            ) from errors[0]
