"""Historical MCP/CLI placeholders decode without altering durable history."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import ValidationError

from tests.workflow.helpers import snapshot
from workflowweave.models import WorkflowSnapshot
from workflowweave.workflow.execution.recovery import prepare_recovery
from workflowweave.workflow.graph.workflow import GRAPH_REVISION
from workflowweave.workflow.storage.facts import SessionStore
from workflowweave.workflow.storage.sessions import SessionView
from workflowweave.workflow.storage.snapshots import parse_historical_snapshot
from workflowweave.workflow.stream.subscriptions.checkpoints import CheckpointArchive


def historical_snapshot():
    data = snapshot(channels=False).model_dump(mode="json")
    data["workflow"]["include_counts"] = True
    data["sources"]["source"].update(
        collector=None, options={}, setters={}, template=None,
        on_missing="notice", on_filtered_empty="notice",
    )
    return data


def test_historical_decode_preserves_input_and_new_input_remains_strict():
    data = historical_snapshot()
    original = deepcopy(data)
    decoded = parse_historical_snapshot(data)
    assert decoded == snapshot(channels=False).model_copy(update={"created_at": decoded.created_at})
    assert data == original
    assert parse_historical_snapshot(decoded.model_dump(mode="json")) == decoded
    with pytest.raises(ValidationError, match="extra_forbidden"):
        WorkflowSnapshot.model_validate(data)


def test_historical_mcp_and_embedded_override_preserve_call_and_scope():
    data = historical_snapshot()
    call = {"kind": "mcp", "server": "logs", "tool": "query", "arguments": {"limit": 10}}
    data["sources"]["source"]["call"] = call
    data["mcp_servers"] = {"logs": {
        "id": "logs", "transport": "stdio", "command": "python", "args": ["logs.py"],
    }}
    data["workflow"]["source_overrides"] = {
        "source": {"source": deepcopy(data["sources"]["source"])},
    }
    original = deepcopy(data)
    decoded = parse_historical_snapshot(data)
    assert decoded.sources["source"].call.model_dump(mode="json") == call
    assert decoded.workflow.source_overrides["source"].source.call == decoded.sources["source"].call
    assert decoded.mcp_servers["logs"].command == "python"
    assert data == original


@pytest.mark.parametrize("field,value", [
    ("collector", "real-collector"), ("options", {"path": "input"}),
    ("setters", {"filter": "custom"}), ("template", "{text}"),
    ("on_missing", "stop"), ("on_filtered_empty", "skip"),
    ("unknown_field", None),
])
def test_nonempty_or_unknown_historical_fields_are_not_silently_discarded(field, value):
    data = historical_snapshot()
    data["sources"]["source"][field] = value
    with pytest.raises(ValidationError) as caught:
        parse_historical_snapshot(data)
    assert ("sources", "source", field) in {issue["loc"] for issue in caught.value.errors()}


async def test_checkpoint_archive_recovery_and_binding_share_historical_decode(tmp_path):
    path = str(tmp_path / "workflows.sqlite3")
    store = SessionStore(path)
    data = historical_snapshot()
    checkpoint = empty_checkpoint()
    checkpoint["channel_values"] = {
        "graph_revision": GRAPH_REVISION,
        "snapshot": data,
        "execution_epoch": "original-epoch",
        "phase": {"stage": "collect", "status": "completed"},
        "shared_input": "original collected text",
        "input_views": [],
    }
    config = {"configurable": {"thread_id": "old-run", "checkpoint_ns": ""}}
    try:
        async with AsyncSqliteSaver.from_conn_string(path) as saver:
            await saver.setup()
            await saver.aput(config, checkpoint, {"source": "input", "step": 0, "parents": {}}, {})
            view = SessionView(store)
            archive = CheckpointArchive(saver, store, view, AsyncMock())
            store.create("old-run", data["workflow"]["id"], parse_historical_snapshot(data).workflow.backup)
            store.write(
                "old-run", "phase:collect:epoch:original-epoch", stage="collect", scope="phase",
                summary={"stage": "collect", "status": "completed", "execution_epoch": "original-epoch"},
                body={
                    "shared_input": "original collected text", "input_views": [],
                    "input_format": {"input_separator": data["workflow"]["input_separator"], "include_counts": True},
                },
            )

            await archive.reconcile("old-run")
            first = store.entries("old-run")
            assert store.entry("old-run", "snapshot")["body"]["snapshot"] == data
            await archive.reconcile("old-run")
            assert store.entries("old-run") == first
            assert (await saver.aget_tuple(config)).checkpoint["channel_values"]["snapshot"] == data
            assert await view.mcp_binding("old-run") == {"servers": {}, "sources": []}

            state = SimpleNamespace(values=checkpoint["channel_values"])
            graph = SimpleNamespace(aget_state=AsyncMock(return_value=state))
            restored, _, _, selected = await prepare_recovery(
                "old-run", saver=saver, store=store, view=view, graph=graph,
            )
            assert restored.sources["source"].call.kind == "cli"
            assert selected is state
            assert store.entries("old-run") == first
    finally:
        store.close()
