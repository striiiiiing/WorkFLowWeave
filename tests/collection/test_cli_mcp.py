import sys

import pytest

from logagent.collection.manager import CollectorManager
from logagent.models import CollectionContext, SourceConfig


async def test_cli_preserves_false_json_and_diagnostics():
    source = SourceConfig(id="cli", call={"kind": "cli", "mode": "argv", "executable": sys.executable,
        "argv": ["-c", "import sys; print('false'); print('diagnostic', file=sys.stderr)"]})
    result = await CollectorManager(None).collect(source, CollectionContext("wf", "session"))
    assert result.status == "success"
    assert result.raw == {"stdout": "false\n", "stderr": "diagnostic\n", "exit_code": 0}


@pytest.mark.parametrize("text", ["0", "false", "null", "[]", "{}"])
async def test_valid_json_is_content(text):
    source = SourceConfig(id="cli", call={"kind": "cli", "mode": "argv", "executable": "printf", "argv": [text]})
    result = await CollectorManager(None).collect(source, CollectionContext("wf", "session"))
    assert result.status == "success" and result.raw["stdout"] == text


async def test_nonzero_and_explicit_shell():
    manager = CollectorManager(None)
    context = CollectionContext("wf", "session")
    result = await manager.collect(SourceConfig(id="cli", call={"kind": "cli", "mode": "shell",
        "command": "printf partial; printf error >&2; exit 2"}), context)
    assert result.status == "failed" and result.raw["stdout"] == "partial" and result.raw["stderr"] == "error"
    result = await manager.collect(SourceConfig(id="cli", call={"kind": "cli", "mode": "argv",
        "executable": "printf", "argv": ["%s", "a | cat"]}), context)
    assert result.raw["stdout"] == "a | cat"


async def test_cli_timeout_keeps_partial_result():
    result = await CollectorManager(None).collect(SourceConfig(id="cli", timeout=0.05,
        call={"kind": "cli", "mode": "shell", "command": "printf before; sleep 10"}), CollectionContext("wf", "session"))
    assert result.status == "timeout" and result.raw["stdout"] == "before"
    assert result.metadata["result_known"] is False


async def test_invalid_utf8_retains_diagnostics_and_reports_encoding_error():
    source = SourceConfig(id="cli", call={"kind": "cli", "mode": "argv",
        "executable": sys.executable,
        "argv": ["-c", "import sys; sys.stdout.buffer.write(b'head\\xff')"]})
    result = await CollectorManager(None).collect(source, CollectionContext("wf", "session"))
    assert result.status == "failed"
    assert result.error.code == "cli_encoding"
    assert result.raw["stdout"] == "head\\xff"
