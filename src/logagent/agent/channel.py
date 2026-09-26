"""Agent-side command and conversation binding for external transports."""

from __future__ import annotations

import asyncio
import inspect

from logagent.agent.commands import AgentChannel, AgentCommand
from logagent.channel.bindings import ChannelBindings
from logagent.errors import LogAgentError


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

    async def process(self, peer: str, command: AgentCommand, *, valid=lambda: True) -> dict:
        action, argument = command.operation()
        async with self._locks.setdefault(peer, asyncio.Lock()):
            if not valid():
                raise LogAgentError("message_interrupted", "消息因更高优先级的停止命令而取消")
            admitted: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()
            self._admitting[peer] = admitted
            try:
                command.session = await self.bindings.current(peer)
                if not valid():
                    raise LogAgentError("message_interrupted", "消息因更高优先级的停止命令而取消")
                if action == "resume":
                    target = argument or command.session
                    if target is None or not await self.bindings.owns(peer, target):
                        raise LogAgentError("session_forbidden", "此会话不属于当前渠道对话")
                if command.session is None and action in {"message", "append"}:
                    created = await self._dispatch(AgentCommand(
                        channel=command.channel, request_id=f"{command.request_id}:new", text="/new",
                    ))
                    command.session = created["result"]["session_id"]
                    await self.bindings.bind(peer, command.session)
                if not valid():
                    raise LogAgentError("message_interrupted", "消息因更高优先级的停止命令而取消")
                response = await self._dispatch(command, valid=valid)
                if response["kind"] == "session":
                    await self.bindings.bind(peer, response["result"]["session_id"])
                result = response["result"]
                admitted.set_result(
                    command.session or (result.get("session_id") if isinstance(result, dict) else None)
                )
                return response
            finally:
                if not admitted.done():
                    admitted.set_result(command.session)
                self._admitting.pop(peer, None)

    async def stop(self, peer: str, command: AgentCommand) -> dict:
        session = await self.bindings.current(peer)
        pending = self._admitting.get(peer)
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
        return await self._dispatch(command)

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
