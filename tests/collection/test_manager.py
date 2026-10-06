"""MCP/CLI collection manager boundaries and concurrent source isolation."""

import asyncio
import math
import sys

import pytest
from pydantic import ValidationError

from workflowweave.collection.manager import CollectorManager
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.mcp.runtime import MCPExecution
from workflowweave.models import CollectionContext, SourceConfig

CONTEXT = CollectionContext("workflow", "session")


def cli_source(ident, program, *, timeout=60, on_error="notice"):
    return SourceConfig(id=ident, timeout=timeout, on_error=on_error, call={
        "kind": "cli", "mode": "argv", "executable": sys.executable, "argv": ["-c", program],
    })


def mcp_source(*, arguments=None, timeout=3):
    return SourceConfig(id="mcp-source", timeout=timeout, call={
        "kind": "mcp", "server": "server", "tool": "echo", "arguments": arguments or {},
    })


class Runtime:
    def __init__(self, execution):
        self.execution = execution
        self.calls = []

    async def call(self, scope, server, tool, arguments, *, context, timeout_seconds):
        self.calls.append((scope, server, tool, arguments, context, timeout_seconds))
        if isinstance(self.execution, Exception):
            raise self.execution
        return self.execution


def execution(status="success", raw=None, *, phase="received", result_known=True):
    return MCPExecution("server", "echo", {}, status, phase, result_known, raw)


def test_validation_is_pure_and_descriptions_are_empty():
    manager = CollectorManager(None)
    source = cli_source("one", "print('value')")
    manager.validate(source)
    assert manager.describe() == []
    assert source.call.argv[-1] == "print('value')"


async def test_missing_mcp_scope_is_a_missing_fact_without_policy_execution():
    runtime = Runtime(WorkFLowWeaveError("mcp_out_of_scope", "not bound"))
    source = mcp_source()
    source.on_missing = "stop"
    result = await CollectorManager(runtime).collect(source, CONTEXT)
    assert result.status == "missing"
    assert result.error.code == "mcp_out_of_scope"
    assert result.raw is None


async def test_mcp_dispatch_preserves_raw_context_and_timeout():
    raw = {"content": [{"type": "text", "text": "false"}], "structuredContent": {"ok": False}}
    runtime = Runtime(execution(raw=raw))
    context = CollectionContext("workflow", "session", mcp_servers={"server": object()})
    source = mcp_source(arguments={"nested": {"value": 1}}, timeout=2)
    result = await CollectorManager(runtime).collect(source, context)
    assert result.status == "success" and result.raw == raw
    scope, server, tool, arguments, sent_context, timeout = runtime.calls[0]
    assert scope == context.mcp_servers
    assert (server, tool, timeout) == ("server", "echo", 2)
    assert arguments == {"nested": {"value": 1}}
    assert sent_context == {
        "workflow_id": "workflow", "session_id": "session", "source_id": "mcp-source",
    }
    result.raw["structuredContent"]["ok"] = True
    assert raw["structuredContent"]["ok"] is False
    assert source.call.arguments == {"nested": {"value": 1}}


@pytest.mark.parametrize("status,expected,error_code,known", [
    ("tool_error", "failed", "mcp_tool_error", True),
    ("failed", "failed", "mcp_failed", False),
    ("timeout", "timeout", "mcp_timeout", False),
])
async def test_mcp_failed_execution_preserves_result_certainty(status, expected, error_code, known):
    runtime = Runtime(execution(status, {"content": [{"type": "text", "text": "partial"}]},
                                phase="dispatched", result_known=known))
    result = await CollectorManager(runtime).collect(mcp_source(), CONTEXT)
    assert result.status == expected and result.error.code == error_code
    assert result.error.details == {"phase": "dispatched", "result_known": known}
    assert result.raw["content"][0]["text"] == "partial"


async def test_empty_mcp_text_has_no_content():
    runtime = Runtime(execution(raw={"content": [{"type": "text", "text": ""}]}))
    result = await CollectorManager(runtime).collect(mcp_source(), CONTEXT)
    assert result.status == "empty" and result.raw["content"][0]["text"] == ""


async def test_one_source_timeout_does_not_cancel_another_source():
    timed, success = await asyncio.gather(
        CollectorManager(None).collect(cli_source("slow", "import time; time.sleep(10)", timeout=0.05), CONTEXT),
        CollectorManager(None).collect(cli_source("fast", "print('ready')"), CONTEXT),
    )
    assert timed.status == "timeout" and timed.metadata["result_known"] is False
    assert success.status == "success" and success.raw["stdout"] == "ready\n"


async def test_caller_cancellation_propagates_and_terminates_cli_process():
    source = cli_source("waiting", "import time; time.sleep(10)")
    task = asyncio.create_task(CollectorManager(None).collect(source, CONTEXT))
    await asyncio.sleep(0.1)
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_concurrent_cli_results_keep_source_identity_and_raw_independent():
    manager = CollectorManager(None)
    sources = [cli_source(ident, f"print({ident!r})") for ident in ("first", "second")]
    results = await asyncio.gather(*(manager.collect(source, CONTEXT) for source in sources))
    assert [result.source_id for result in results] == ["first", "second"]
    assert [result.raw["stdout"] for result in results] == ["first\n", "second\n"]
    results[0].raw["stdout"] = "changed"
    assert results[1].raw["stdout"] == "second\n"


async def test_mutated_source_cannot_hide_invalid_json():
    source = mcp_source()
    source.call.arguments["bad"] = math.nan
    with pytest.raises(ValidationError):
        await CollectorManager(None).collect(source, CONTEXT)
