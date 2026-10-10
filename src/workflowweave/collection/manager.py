"""Acquire raw MCP/CLI results without Workflow representation or business counts."""
from __future__ import annotations

import asyncio
import os
import signal
from dataclasses import asdict
from typing import Protocol

from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import CollectionResult, ErrorInfo, SourceConfig, copy_model


class ReferenceFiles(Protocol):
    def validate_path(self, relative: str): ...
    def read_text(self, relative: str) -> str: ...
    def create_text(self, relative: str, content: bytes) -> None: ...


class CollectorManager:
    def __init__(self, mcp_runtime, files: ReferenceFiles | None = None):
        self.mcp = mcp_runtime
        self.files = files

    def validate(self, source):
        source = copy_model(source)
        if source.call.kind == "file":
            if self.files is None:
                raise WorkFLowWeaveError("configuration_unavailable", "文件引用服务尚未装配")
            self.files.validate_path(source.call.path)

    async def collect(self, source: SourceConfig, context):
        source = copy_model(source)
        try:
            if source.call.kind == "cli":
                return await self._cli(source)
            if source.call.kind == "file":
                return await self._file(source)
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
                has_content = execution.count_state == "available" and raw is not None and (
                    raw.get("_meta", {}).get("workflowweave_count", 0) > 0
                ) or raw is not None and execution.count_state == "count_unavailable" and (
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
        except WorkFLowWeaveError as exc:
            return CollectionResult(source_id=source.id,
                                    status="failed", error=exc.info)

    async def _file(self, source):
        metadata = {"kind": "file", "file_type": source.call.file_type, "path": source.call.path}
        try:
            if self.files is None:
                raise WorkFLowWeaveError("configuration_unavailable", "文件引用服务尚未装配")
            async with asyncio.timeout(source.timeout):
                text = await asyncio.to_thread(self.files.read_text, source.call.path)
            return CollectionResult(
                source_id=source.id,
                status="empty" if text == "" else "success",
                raw={"text": text},
                metadata={**metadata, "result_known": True},
            )
        except TimeoutError:
            return CollectionResult(
                source_id=source.id, status="timeout", raw=None,
                error=ErrorInfo(code="file_timeout", message="文件读取超时"),
                metadata={**metadata, "result_known": False},
            )
        except WorkFLowWeaveError as exc:
            return CollectionResult(
                source_id=source.id, status="failed", raw=None, error=exc.info,
                metadata={**metadata, "result_known": True},
            )

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
