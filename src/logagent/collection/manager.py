"""Acquire raw MCP/CLI results without Workflow representation or business counts."""
from __future__ import annotations

import asyncio
import os
import signal
from dataclasses import asdict

from logagent.errors import LogAgentError
from logagent.models import CollectionResult, ErrorInfo, SourceConfig, copy_model


class CollectorManager:
    def __init__(self, mcp_runtime):
        # The merged runtime keeps the old registry argument for lifecycle
        # wiring, but MCP/CLI sources are the only workflow execution form.
        self.mcp = mcp_runtime if hasattr(mcp_runtime, "call") else None
        self._legacy = mcp_runtime if self.mcp is None else None

    def validate(self, source):
        copy_model(source)

    def describe(self):
        return []

    def reload_register(self, registry):
        """Collector plugins no longer participate in collection."""

    async def collect(self, source: SourceConfig, context):
        source = copy_model(source)
        try:
            if source.call is None:
                return await self._collect_legacy(source, context)
            if source.call.kind == "cli":
                return await self._cli(source)
            call = source.call
            execution = await self.mcp.call(
                context.mcp_servers or {}, call.server, call.tool, call.arguments,
                context={"workflow_id": context.workflow_id, "session_id": context.session_id,
                         "source_id": source.id}, timeout_seconds=source.timeout,
            )
            metadata = asdict(execution)
            metadata.pop("raw")
            raw = execution.raw
            status = execution.status
            if status == "success":
                has_content = raw is not None and (
                    "structuredContent" in raw or any(
                        block.get("type") != "text" or block.get("text") != ""
                        for block in raw.get("content", [])
                    )
                )
                status = "success" if has_content else "empty"
            elif status == "tool_error":
                status = "failed"
            error = None if status in {"success", "empty"} else ErrorInfo(
                code="mcp_" + execution.status, message="MCP 获取失败",
                details={"phase": execution.phase, "result_known": execution.result_known},
            )
            return CollectionResult(source_id=source.id, status=status,
                                    raw=raw, error=error, metadata=metadata)
        except LogAgentError as exc:
            return CollectionResult(source_id=source.id,
                                    status="missing" if exc.code in {
                                        "mcp_out_of_scope", "mcp_tool_missing", "mcp_disabled",
                                    } else "failed", error=exc.info)

    async def _collect_legacy(self, source, context):
        """Compatibility boundary for un-migrated history/test resources.

        New persisted workflows must use ``call``; this narrow adapter keeps
        the read-only History Collector and explicit legacy fixtures usable
        while the MCP/CLI execution path remains the sole new contract.
        """
        register = self._legacy
        collector = register.get(source.collector) if register is not None else None
        if collector is None:
            return CollectionResult(
                source_id=source.id, status="missing",
                error=ErrorInfo(code="collector_missing", message="来源插件不可用"),
            )
        try:
            raw = await collector.collect(source.options, source.setters, context)
            data = raw.model_dump(mode="json") if hasattr(raw, "model_dump") else raw
            return CollectionResult(source_id=source.id, **data)
        except LogAgentError as exc:
            return CollectionResult(source_id=source.id, status="failed", error=exc.info)

    async def _cli(self, source):
        call = source.call
        process = None
        communicate = None
        try:
            async with asyncio.timeout(source.timeout):
                kwargs = dict(cwd=call.cwd, stdout=asyncio.subprocess.PIPE,
                              stderr=asyncio.subprocess.PIPE, start_new_session=True)
                if call.mode == "argv":
                    process = await asyncio.create_subprocess_exec(
                        call.executable, *call.argv, **kwargs,
                    )
                else:
                    process = await asyncio.create_subprocess_shell(call.command, **kwargs)
                communicate = asyncio.create_task(process.communicate())
                stdout, stderr = await asyncio.shield(communicate)
            invalid_encoding = False
            try:
                output = stdout.decode("utf-8")
                diagnostic = stderr.decode("utf-8")
            except UnicodeDecodeError:
                invalid_encoding = True
                output = stdout.decode("utf-8", errors="backslashreplace")
                diagnostic = stderr.decode("utf-8", errors="backslashreplace")
            raw = {"stdout": output, "stderr": diagnostic, "exit_code": process.returncode}
            status = "failed" if process.returncode or invalid_encoding else "success" if stdout else "empty"
            return CollectionResult(
                source_id=source.id, status=status, raw=raw,
                error=(ErrorInfo(code="cli_encoding", message="CLI 输出不是有效 UTF-8，原始字节已转义保留")
                       if invalid_encoding else ErrorInfo(code="cli_exit", message="CLI 非零退出",
                           details={"exit_code": process.returncode}) if process.returncode else None),
                metadata={"kind": "cli", "mode": call.mode, "result_known": True},
            )
        except (TimeoutError, asyncio.CancelledError) as exc:
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                stdout, stderr = await communicate if communicate else await process.communicate()
            else:
                stdout, stderr = b"", b""
            if isinstance(exc, asyncio.CancelledError):
                raise
            return CollectionResult(
                source_id=source.id, status="timeout",
                raw={"stdout": stdout.decode("utf-8", errors="backslashreplace"),
                     "stderr": stderr.decode("utf-8", errors="backslashreplace"),
                     "exit_code": process.returncode if process else None},
                error=ErrorInfo(code="cli_timeout", message="CLI 超时，进程组已终止"),
                metadata={"result_known": False, "phase": "dispatched" if process else "start"},
            )
        except OSError as exc:
            return CollectionResult(source_id=source.id, status="failed",
                                    error=ErrorInfo(code="cli_failed", message=str(exc)))
