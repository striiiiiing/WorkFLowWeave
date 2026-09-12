"""Cross-operation acceptance tests for the public configuration contract."""

import asyncio
import json
import os
import threading
from pathlib import Path

import pytest
from pydantic import ValidationError

from logagent.config import ResourceStore
from logagent.errors import LogAgentError
from logagent.models import (
    AIConfig,
    AnalysisTask,
    ChannelConfig,
    SetterTemplate,
    SourceConfig,
    WorkflowDefinition,
    WorkflowSnapshot,
)


async def seed(store: ResourceStore) -> WorkflowDefinition:
    await store.save("setters", SetterTemplate(id="template", collector="mock", setters={"fields": ["text"]}))
    await store.save(
        "sources",
        SourceConfig(id="source", collector="mock", template="template", options={"items": [{"text": "original"}]}),
    )
    await store.save("ai", AIConfig(id="model", provider="mock", model="echo"))
    workflow = WorkflowDefinition(
        id="workflow", sources=["source"], analyses=[AnalysisTask(id="summary", ai="model", prompt="{input}")]
    )
    await store.save("workflows", workflow)
    return workflow


@pytest.mark.asyncio
async def test_concurrent_create_accepts_exactly_one_writer(tmp_path):
    store = ResourceStore(tmp_path)
    results = await asyncio.gather(
        *(store.save("ai", AIConfig(id="same", provider="mock", model=f"model-{i}"), mode="create") for i in range(8)),
        return_exceptions=True,
    )
    accepted = [result for result in results if not isinstance(result, BaseException)]
    rejected = [result for result in results if isinstance(result, BaseException)]
    assert len(accepted) == 1
    assert len(rejected) == 7
    assert all(isinstance(result, LogAgentError) for result in rejected)
    assert (await store.get("ai", "same")).model == accepted[0].model


@pytest.mark.asyncio
async def test_delete_racing_new_reference_never_leaves_dangling_resource(tmp_path):
    store = ResourceStore(tmp_path)
    await store.save("ai", AIConfig(id="model", provider="mock", model="echo"))
    await store.save("sources", SourceConfig(id="source", collector="mock"))
    workflow = WorkflowDefinition(id="workflow", sources=["source"], analyses=[AnalysisTask(id="summary", ai="model")])
    outcomes = await asyncio.gather(
        store.save("workflows", workflow, mode="create"),
        store.delete("sources", "source"),
        return_exceptions=True,
    )
    assert sum(isinstance(result, LogAgentError) for result in outcomes) == 1
    workflows = await store.list("workflows")
    if workflows:
        snapshot = await store.snapshot("workflow")
        assert snapshot.sources["source"].id == "source"
    else:
        assert await store.list("sources") == []


@pytest.mark.asyncio
async def test_resolve_is_read_only_and_preserves_saved_definition(tmp_path):
    store = ResourceStore(tmp_path)
    workflow = await seed(store)
    proposed = workflow.model_copy(deep=True, update={"name": "not saved"})
    snapshot = await store.resolve(proposed)
    assert isinstance(snapshot, WorkflowSnapshot)
    assert snapshot.workflow.name == "not saved"
    assert (await store.get("workflows", "workflow")).name == workflow.name

    invalid = proposed.model_copy(update={"sources": ["does-not-exist"]})
    with pytest.raises(LogAgentError):
        await store.resolve(invalid)
    assert (await store.get("workflows", "workflow")).sources == ["source"]


@pytest.mark.asyncio
async def test_snapshot_stays_detached_across_template_updates_and_restart(tmp_path):
    store = ResourceStore(tmp_path)
    await seed(store)
    first = await store.snapshot("workflow")
    await store.save("setters", SetterTemplate(id="template", collector="mock", setters={"fields": []}))
    second = await ResourceStore(tmp_path).snapshot("workflow")
    assert first.sources["source"].setters["fields"] == ["text"]
    assert second.sources["source"].setters["fields"] == []
    second.sources["source"].options["items"][0]["text"] = "local mutation"
    assert (await store.get("sources", "source")).options["items"][0]["text"] == "original"
    assert first.sources["source"].options["items"][0]["text"] == "original"


@pytest.mark.asyncio
async def test_replacing_template_cannot_invalidate_existing_source(tmp_path):
    store = ResourceStore(tmp_path)
    await seed(store)
    with pytest.raises(LogAgentError):
        await store.save("setters", SetterTemplate(id="template", collector="history"), mode="replace")
    assert (await store.get("setters", "template")).collector == "mock"
    assert (await store.snapshot("workflow")).sources["source"].collector == "mock"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["sources", "ai", "channels"])
@pytest.mark.parametrize("damage", ["missing", "extra", "wrong_id"])
async def test_serialized_snapshots_enforce_resource_integrity(tmp_path, kind, damage):
    store = ResourceStore(tmp_path)
    workflow = await seed(store)
    await store.save("channels", ChannelConfig(id="report", channel="file"))
    workflow.channels = ["report"]
    snapshot = await store.resolve(workflow)
    serialized = snapshot.model_dump_json()
    assert WorkflowSnapshot.model_validate_json(serialized) == snapshot

    data = json.loads(serialized)
    key = next(iter(data[kind]))
    if damage == "missing":
        del data[kind][key]
    elif damage == "extra":
        data[kind]["unrelated"] = {**data[kind][key], "id": "unrelated"}
    else:
        data[kind][key]["id"] = "different"
    with pytest.raises(ValidationError):
        WorkflowSnapshot.model_validate_json(json.dumps(data))


@pytest.mark.asyncio
async def test_snapshots_preserve_plugin_owned_path_semantics(tmp_path):
    store = ResourceStore(tmp_path / "resources", base_dir=tmp_path)
    workflow = await seed(store)
    source = await store.get("sources", "source")
    source.collector = "custom"
    source.template = None
    source.options = {"path": "src/main.py", "result_path": "$.items", "remote_path": "s3://bucket/key"}
    await store.save("sources", source)
    await store.save("channels", ChannelConfig(id="custom", channel="custom", options={"path": "/api/post"}))
    workflow.channels = ["custom"]
    snapshot = await store.resolve(workflow)
    assert snapshot.sources["source"].options == source.options
    assert snapshot.channels["custom"].options == {"path": "/api/post"}


@pytest.mark.asyncio
async def test_cancelled_disk_write_cannot_overtake_a_newer_save(tmp_path, monkeypatch):
    store = ResourceStore(tmp_path)
    await store.save("ai", AIConfig(id="model", provider="mock", model="initial"))
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = threading.Event()
    original_replace = os.replace

    def delayed_replace(source, destination, *args, **kwargs):
        if json.loads(Path(source).read_text()).get("model") == "slow":
            loop.call_soon_threadsafe(started.set)
            if not release.wait(5):
                raise TimeoutError("test did not release the blocked write")
        return original_replace(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "replace", delayed_replace)
    slow = asyncio.create_task(store.save("ai", AIConfig(id="model", provider="mock", model="slow")))
    newer = None
    try:
        await asyncio.wait_for(started.wait(), 3)
        slow.cancel()
        newer = asyncio.create_task(store.save("ai", AIConfig(id="model", provider="mock", model="newest")))
        await asyncio.sleep(0.02)
        assert not newer.done(), "cancellation released the resource lock while disk I/O was still active"
    finally:
        release.set()
        await asyncio.gather(slow, *([newer] if newer is not None else []), return_exceptions=True)
    assert slow.cancelled()
    assert (await store.get("ai", "model")).model == "newest"
