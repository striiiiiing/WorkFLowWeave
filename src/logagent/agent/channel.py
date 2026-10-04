"""Agent-side command and conversation binding for external transports."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass

from logagent.agent.commands import AgentChannel, AgentCommand
from logagent.channel.bindings import ChannelBindings, InstanceBinding
from logagent.errors import LogAgentError


@dataclass(frozen=True)
class ProcessedInput:
    response: dict
    binding: InstanceBinding


class AgentChannelProcessor:
    def __init__(self, commands: AgentChannel, bindings: ChannelBindings):
        self.commands = commands
        self.bindings = bindings
        self._locks: dict[str, asyncio.Lock] = {}
        self._admitting: dict[str, asyncio.Future[str | None]] = {}

    async def _dispatch(self, command: AgentCommand, *, valid=None):
        if "valid" not in inspect.signature(self.commands.dispatch).parameters:
            return await self.commands.dispatch(command)
        return await self.commands.dispatch(command, valid=valid)

    async def bind(self, channel_id: str, session_id: str | None) -> InstanceBinding:
        async with self._locks.setdefault(channel_id, asyncio.Lock()):
            if session_id is not None:
                await self.commands.get_session(session_id)
            return await self.bindings.bind_instance(channel_id, session_id)

    async def process(self, channel_id: str, command: AgentCommand, *,
                      binding: InstanceBinding, valid=lambda: True) -> ProcessedInput:
        action, _ = command.operation()
        async with self._locks.setdefault(channel_id, asyncio.Lock()):
            if self.bindings.instance(channel_id) != binding:
                raise LogAgentError("channel_binding_changed", "输入受理后渠道绑定已变更")
            if not valid():
                raise LogAgentError("message_interrupted", "消息因更高优先级的停止命令而取消")
            admitted: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()
            self._admitting[channel_id] = admitted
            try:
                command.session = binding.session_id
                if not valid():
                    raise LogAgentError("message_interrupted", "消息因更高优先级的停止命令而取消")
                if command.session is None and action in {"message", "append", "compact", "fork"}:
                    raise LogAgentError("channel_unbound", "渠道实例尚未绑定对话，请绑定或使用 /resume")
                if not valid():
                    raise LogAgentError("message_interrupted", "消息因更高优先级的停止命令而取消")
                response = await self._dispatch(command, valid=valid)
                if response["kind"] == "session":
                    binding = await self.bindings.bind_instance(
                        channel_id, response["result"]["session_id"],
                    )
                result = response["result"]
                admitted.set_result(
                    command.session or (result.get("session_id") if isinstance(result, dict) else None)
                )
                return ProcessedInput(response, binding)
            finally:
                if not admitted.done():
                    admitted.set_result(command.session)
                self._admitting.pop(channel_id, None)

    async def stop(self, channel_id: str, command: AgentCommand, *,
                   binding: InstanceBinding) -> ProcessedInput:
        if self.bindings.instance(channel_id) != binding:
            raise LogAgentError("channel_binding_changed", "输入受理后渠道绑定已变更")
        session = binding.session_id
        pending = self._admitting.get(channel_id)
        if session is not None:
            command.session = session
            await self._dispatch(command)
        if pending is not None:
            # The first input may be between session creation and turn admission.
            # Wait for its short admission segment, then cancel the actual turn.
            session = await asyncio.shield(pending) or session
        if session is None:
            raise LogAgentError("invalid_argument", "此命令需要 session")
        command.session = session
        return ProcessedInput(await self._dispatch(command), binding)

    async def dispatch_web(self, peer: str, command: AgentCommand, *, valid) -> dict:
        async with self._locks.setdefault(peer, asyncio.Lock()):
            if not valid():
                raise LogAgentError("message_interrupted", "消息因更高优先级的停止命令而取消")
            admitted: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()
            self._admitting[peer] = admitted
            try:
                response = await self._dispatch(command, valid=valid)
                admitted.set_result(command.session)
                return response
            finally:
                if not admitted.done():
                    admitted.set_result(command.session)
                self._admitting.pop(peer, None)

    async def stop_web(self, peer: str, command: AgentCommand) -> dict:
        pending = self._admitting.get(peer)
        if pending is not None and command.session is not None:
            await self._dispatch(command)
            await asyncio.shield(pending)
        return await self._dispatch(command)
