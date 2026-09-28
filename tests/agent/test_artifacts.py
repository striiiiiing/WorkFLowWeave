import json

from logagent.agent.artifacts import ArtifactStore, json_text
from logagent.agent.config import AgentConfig
from logagent.agent.workspace import WorkspaceBackend


async def store_for(tmp_path):
    workspace = WorkspaceBackend(tmp_path / "workspace", tmp_path / "runtime")
    await workspace.initialize()
    return ArtifactStore(workspace)


async def save(store, result, **options):
    return await store.save(result, session_id="session", turn_id="turn", tool_call_id="call",
                            count_tokens=len, **options)


async def test_file_preview_preserves_complete_lines_and_continuation(tmp_path):
    store = await store_for(tmp_path)
    lines = [f"line {i} " + "x" * 100 + "\n" for i in range(20)]
    raw = {"status": "success", "kind": "file", "path": "Memory/day.md", "hash": "hash",
           "content": "".join(lines), "offset": 10, "next_offset": 30, "total_lines": 100}
    result = await save(store, raw, config=AgentConfig(preview_tokens=700))
    shown = len(result["content"].splitlines())
    assert 0 < shown < len(lines)
    assert result["content"] == "".join(lines[:shown])
    assert result["next_offset"] == 10 + shown
    assert result["truncated"] and len(json_text(result)) <= 700
    assert json.loads((store.workspace.runtime / result["artifact_path"]).read_text()) == raw


async def test_oversized_schema_is_readable_and_never_returned_as_broken_json(tmp_path):
    store = await store_for(tmp_path)
    schema = {"type": "object", "properties": {
        "token": {"type": "integer", "description": "Pagination cursor"},
        "text": {"type": "string", "description": "x" * 3000},
    }}
    raw = {"status": "success", "schema": schema}
    result = await save(store, raw, config=AgentConfig(preview_tokens=700), schema_output=True)
    assert result["status"] == "success" and result["truncated"]
    assert "read" in result["preview"]
    assert json.loads((store.workspace.runtime / result["artifact_path"]).read_text()) == raw
    failed = await save(store, raw, config=AgentConfig(preview_tokens=700),
                        schema_output=True, read_enabled=False)
    assert failed["status"] == "output_budget_exceeded"
    assert failed["preview"] == ""


async def test_disk_limit_is_explicit_and_partial_output_remains_utf8(tmp_path):
    store = await store_for(tmp_path)
    result = await save(store, {"status": "success", "text": "中文字" * 1000},
                        config=AgentConfig(output_bytes=511))
    assert result["status"] == "output_limit_exceeded" and result["truncated"]
    path = store.workspace.runtime / result["artifact_path"]
    assert path.name.endswith(".partial.txt")
    assert path.read_text() and path.stat().st_size == result["saved_bytes"] <= 511


async def test_credentials_are_redacted_in_complete_artifact_and_preview(tmp_path):
    store = await store_for(tmp_path)
    result = await save(store, {"status": "success", "api_key": "do-not-save",
                               "text": "Authorization: Bearer do-not-save"}, config=AgentConfig())
    full = (store.workspace.runtime / result["artifact_path"]).read_text()
    assert "do-not-save" not in full and "do-not-save" not in str(result)
    assert "[REDACTED]" in full


async def test_mcp_result_keeps_exact_raw_content_in_full_artifact(tmp_path):
    store = await store_for(tmp_path)
    raw = {"status": "success", "raw": {"content": [
        {"type": "text", "text": "api_key is a field name, not a credential"}
    ], "structuredContent": {"api_key": "source-data"}, "isError": False}}
    result = await save(store, raw, config=AgentConfig(preview_tokens=700), preserve_full=True)
    saved = json.loads((store.workspace.runtime / result["artifact_path"]).read_text())
    assert saved == raw
