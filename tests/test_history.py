import asyncio
from datetime import timedelta

import pytest
from test_archive import NOW, save_envelope, write_session

from logagent.archive import FileArchiveReader
from logagent.collection.history import HistoryCollector
from logagent.errors import LogAgentError
from logagent.models import (
    AnalysisArtifact,
    AnalysisResult,
    CollectionArtifact,
    CollectionContext,
    ErrorInfo,
    FinalArtifact,
    Notification,
    SessionRecord,
)
from logagent.schema import validate_schema


def record(session_id, *, time=NOW, status="completed", workflow_id="workflow", frozen=True):
    return SessionRecord(
        id=session_id,
        workflow_id=workflow_id,
        status=status,
        created_at=time,
        updated_at=time,
        output_frozen=frozen,
    )


def final(session_id, text="saved content"):
    return FinalArtifact(
        outputs=[Notification(session_id=session_id, output_id="analysis", text=text)]
    )


class ReadOnlyArchive:
    """Expose only reader methods; any accidental workflow call must fail."""

    def __init__(self, records=(), artifacts=None):
        self.records = list(records)
        self.artifacts = artifacts or {}
        self.list_calls = []
        self.load_calls = []

    async def list(self, workflow_id=None, limit=100):
        self.list_calls.append((workflow_id, limit))
        return self.records

    async def load_artifact(self, session_id, name):
        self.load_calls.append((session_id, name))
        value = self.artifacts.get((session_id, name), final(session_id))
        if isinstance(value, Exception):
            raise value
        return value

    async def get(self, session_id):
        raise AssertionError("History already has the selected management record")

    async def availability(self, session_id):
        raise AssertionError("History should verify only the requested artifact")


def context(archive=None, *, session_id="current"):
    return CollectionContext(workflow_id="caller", session_id=session_id, archive=archive)


async def collect(archive, **options):
    return await HistoryCollector().collect(
        {"workflow_id": "workflow", **options}, {}, context(archive)
    )


def test_schema_and_validation_are_complete_pure_and_independent():
    collector = HistoryCollector()
    validate_schema(collector.options_schema)
    validate_schema(collector.setters_schema)
    assert collector.options_schema["required"] == ["workflow_id"]
    for rule in collector.options_schema["properties"].values():
        assert rule["type"] and rule["description"]
    assert "utf8_bytes_v1" in collector.options_schema["description"]
    assert collector.setters_schema["additionalProperties"] is False
    assert collector.fields == []
    options = {"workflow_id": "workflow"}
    collector.validate(options, {})
    assert options == {"workflow_id": "workflow"}
    collector.options_schema["properties"]["workflow_id"]["description"] = "changed"
    assert (
        HistoryCollector().options_schema["properties"]["workflow_id"]["description"] != "changed"
    )


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"workflow_id": "../workflow"},
        {"workflow_id": "workflow\n"},
        {"workflow_id": "workflow", "limit": 0},
        {"workflow_id": "workflow", "limit": True},
        {"workflow_id": "workflow", "limit": 1.0},
        {"workflow_id": "workflow", "token_budget": -1},
        {"workflow_id": "workflow", "token_budget": 1.0},
        {"workflow_id": "workflow", "token_budget": "100"},
        {"workflow_id": "workflow", "artifact": "snapshot"},
        {"workflow_id": "workflow", "unknown": "private input"},
        {"workflow_id": "workflow", "start_time": "2026-09-13T12:00:00"},
        {
            "workflow_id": "workflow",
            "start_time": "2026-09-14T00:00:00Z",
            "end_time": "2026-09-13T00:00:00Z",
        },
    ],
)
async def test_direct_collect_rejects_invalid_options_before_archive_io(options):
    archive = ReadOnlyArchive()
    with pytest.raises(LogAgentError) as error:
        await HistoryCollector().collect(options, {}, context(archive))
    assert error.value.code == "invalid_config"
    assert archive.list_calls == archive.load_calls == []
    assert "private input" not in error.value.info.model_dump_json()


@pytest.mark.parametrize("setters", [{"fields": []}, {"filter": {}}, {"group": "workflow_id"}])
async def test_unimplemented_setters_are_not_accepted(setters):
    archive = ReadOnlyArchive()
    with pytest.raises(LogAgentError):
        await HistoryCollector().collect({"workflow_id": "workflow"}, setters, context(archive))
    assert archive.list_calls == []


async def test_absent_archive_dependency_is_missing():
    result = await HistoryCollector().collect({"workflow_id": "workflow"}, {}, context())
    assert result.status == "missing"
    assert result.error.code == "history_archive_missing"
    assert result.count == 0 and not result.text and not result.items


async def test_default_final_selection_excludes_current_active_and_other_workflow():
    archive = ReadOnlyArchive(
        [
            record("a"),
            record("current", time=NOW + timedelta(hours=3)),
            record("other", workflow_id="other", time=NOW + timedelta(hours=4)),
            record("running", status="running", time=NOW + timedelta(hours=2)),
            record("created", status="created", time=NOW + timedelta(hours=1)),
            record("z"),
        ]
    )
    result = await collect(archive)
    assert result.status == "success" and result.count == 1
    assert result.items[0]["session_id"] == "z"
    assert archive.list_calls == [("workflow", None)]
    assert archive.load_calls == [("z", "final")]
    assert [item.id for item in archive.records] == [
        "a",
        "current",
        "other",
        "running",
        "created",
        "z",
    ]


@pytest.mark.parametrize("status", ["completed", "partial", "failed", "cancelled", "interrupted"])
async def test_all_existing_terminal_statuses_can_supply_history(status):
    result = await collect(ReadOnlyArchive([record("previous", status=status)]))
    assert result.status == "success"


async def test_time_window_is_inclusive_normalized_and_intersects_recent_limit():
    archive = ReadOnlyArchive(
        [
            record("before", time=NOW - timedelta(hours=2)),
            record("start", time=NOW - timedelta(hours=1)),
            record("middle", time=NOW - timedelta(minutes=30)),
            record("end", time=NOW),
            record("after", time=NOW + timedelta(hours=1)),
        ]
    )
    result = await collect(
        archive,
        start_time="2026-09-13T19:00:00+08:00",
        end_time="2026-09-13T12:00:00Z",
        limit=2,
    )
    assert [item["session_id"] for item in result.items] == ["end", "middle"]
    result = await collect(
        archive,
        start_time="2026-09-13T19:00:00+08:00",
        end_time="2026-09-13T12:00:00Z",
        limit=10,
    )
    assert [item["session_id"] for item in result.items] == ["end", "middle", "start"]


async def test_no_matching_session_is_empty_but_empty_projection_is_filtered_empty():
    result = await collect(ReadOnlyArchive([record("active", status="running")]))
    assert result.status == "empty"
    archive = ReadOnlyArchive(
        [record("new", time=NOW), record("old", time=NOW - timedelta(days=1))],
        {("new", "collection"): CollectionArtifact(shared_input=" \n", results=[])},
    )
    result = await collect(archive, artifact="collection")
    assert result.status == "filtered_empty" and result.count == 0
    assert archive.load_calls == [("new", "collection")]
    assert result.metadata["used_bytes"] == 0


async def test_collection_uses_original_shared_input_as_one_complete_history_record():
    source_text = "原始共享输入\n\nwith delimiters intact"
    archive = ReadOnlyArchive(
        [record("previous")],
        {("previous", "collection"): CollectionArtifact(shared_input=source_text, results=[])},
    )
    result = await collect(archive, artifact="collection")
    assert result.count == 1
    assert result.items[0]["text"] == source_text
    assert result.text.endswith(source_text)
    assert "workflow=workflow session=previous" in result.text


async def test_analysis_only_uses_successes_in_declared_order_and_counts_sessions():
    artifact = AnalysisArtifact(
        order=["second", "first", "failed"],
        results=[
            AnalysisResult(task_id="first", status="success", text="first result"),
            AnalysisResult(
                task_id="failed",
                status="failed",
                error=ErrorInfo(code="failed", message="private failure"),
            ),
            AnalysisResult(task_id="second", status="success", text="second result"),
        ],
    )
    archive = ReadOnlyArchive([record("previous")], {("previous", "analysis"): artifact})
    result = await collect(archive, artifact="analysis")
    assert result.count == 1
    assert result.text.index("second result") < result.text.index("first result")
    assert "private failure" not in result.text
    assert "failed" not in result.items[0]["text"]


async def test_final_preserves_frozen_output_order():
    artifact = FinalArtifact(
        outputs=[
            Notification(session_id="previous", output_id="two", text="second output"),
            Notification(session_id="previous", output_id="one", text="first output"),
        ]
    )
    result = await collect(ReadOnlyArchive([record("previous")], {("previous", "final"): artifact}))
    assert result.count == 1
    assert result.text.index("second output") < result.text.index("first output")


async def test_unfrozen_final_is_missing_without_reading_its_body():
    archive = ReadOnlyArchive([record("previous", frozen=False)])
    result = await collect(archive)
    assert result.status == "missing"
    assert result.error.details["reason"] == "not_created"
    assert result.error.details["cause"] == "unfrozen"
    assert archive.load_calls == []


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (reason, "missing")
        for reason in (
            "disabled",
            "out_of_scope",
            "not_created",
            "missing",
            "expired",
            "write_failed",
        )
    ]
    + [("corrupt", "failed")],
)
async def test_unavailable_selected_content_is_not_skipped_and_does_not_leak_partial_body(
    reason, expected
):
    archive = ReadOnlyArchive(
        [
            record("first", time=NOW),
            record("broken", time=NOW - timedelta(minutes=1)),
            record("older", time=NOW - timedelta(minutes=2)),
        ],
        {
            ("first", "final"): final("first", "private partial body"),
            ("broken", "final"): LogAgentError(
                "artifact_unavailable",
                "private failed body",
                {"reason": reason, "body": "private diagnostic body"},
            ),
        },
    )
    result = await collect(archive, limit=3)
    assert result.status == expected
    assert result.count == 0 and result.items == [] and result.text == ""
    assert result.metadata["used_bytes"] == 0
    assert archive.load_calls == [("first", "final"), ("broken", "final")]
    assert "private" not in result.model_dump_json()


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("private /path content"),
        LogAgentError("archive_unavailable", "private /path content"),
    ],
)
async def test_unexpected_and_infrastructure_failures_are_structured_and_redacted(error):
    archive = ReadOnlyArchive([record("previous")], {("previous", "final"): error})
    result = await collect(archive)
    assert result.status == "failed" and result.error is not None
    assert "private" not in result.model_dump_json()
    assert "/path" not in result.model_dump_json()


@pytest.mark.parametrize("value", [{"body": "private"}, ["private"]])
async def test_malformed_archive_error_details_do_not_cause_a_second_exception(value):
    error = LogAgentError("artifact_unavailable", "private", {"reason": value, "cause": value})
    result = await collect(ReadOnlyArchive([record("previous")], {("previous", "final"): error}))
    assert result.status == "failed"
    assert "private" not in result.model_dump_json()


@pytest.mark.parametrize(
    "body",
    [
        CollectionArtifact(shared_input="wrong kind", results=[]),
        final("different", "private other output"),
    ],
)
async def test_wrong_artifact_type_or_session_is_failed(body):
    result = await collect(ReadOnlyArchive([record("previous")], {("previous", "final"): body}))
    assert result.status == "failed"
    assert result.error.details["reason"] == "corrupt"
    assert "private" not in result.model_dump_json()


async def test_budget_counts_final_utf8_bytes_including_markers_and_separators():
    records = [record("new"), record("old", time=NOW - timedelta(days=1))]
    bodies = {("new", "final"): final("new", "中文数据"), ("old", "final"): final("old", "older")}
    full = await collect(ReadOnlyArchive(records, bodies), limit=2)
    one = await collect(ReadOnlyArchive(records, bodies), limit=1)
    exact = len(full.text.encode("utf-8"))
    assert exact > len(full.text)
    result = await collect(ReadOnlyArchive(records, bodies), limit=2, token_budget=exact)
    assert result.count == 2 and result.text == full.text
    assert result.metadata == {
        "artifact": "final",
        "budget_algorithm": "utf8_bytes_v1",
        "token_budget": exact,
        "used_bytes": exact,
        "truncated": False,
    }
    truncated = await collect(ReadOnlyArchive(records, bodies), limit=2, token_budget=exact - 1)
    assert truncated.count == 1 and truncated.text == one.text
    assert truncated.metadata["used_bytes"] == len(one.text.encode("utf-8"))
    assert truncated.metadata["truncated"] is True


@pytest.mark.parametrize("budget", [0, 1, 100])
async def test_first_record_that_does_not_fit_returns_filtered_empty_without_skipping_to_older(
    budget,
):
    archive = ReadOnlyArchive(
        [record("new"), record("old", time=NOW - timedelta(days=1))],
        {("new", "final"): final("new", "large" * 100), ("old", "final"): final("old", "tiny")},
    )
    result = await collect(archive, limit=2, token_budget=budget)
    assert result.status == "filtered_empty" and result.count == 0
    assert result.metadata["used_bytes"] == 0 and result.metadata["truncated"] is True
    assert archive.load_calls == [("new", "final")]


async def test_truncate_keeps_a_prefix_instead_of_packing_smaller_older_records():
    records = [
        record("one"),
        record("two", time=NOW - timedelta(minutes=1)),
        record("three", time=NOW - timedelta(minutes=2)),
    ]
    bodies = {
        ("one", "final"): final("one", "small"),
        ("two", "final"): final("two", "large" * 1000),
        ("three", "final"): final("three", "tiny"),
    }
    archive = ReadOnlyArchive(records, bodies)
    result = await collect(archive, limit=3, token_budget=500)
    assert result.count == 1 and result.items[0]["session_id"] == "one"
    assert archive.load_calls == [("one", "final"), ("two", "final")]


async def test_overflow_error_returns_no_partial_text_or_items():
    archive = ReadOnlyArchive(
        [record("one"), record("two", time=NOW - timedelta(minutes=1))],
        {
            ("one", "final"): final("one", "private first"),
            ("two", "final"): final("two", "private" * 1000),
        },
    )
    result = await collect(archive, limit=2, token_budget=500, overflow="error")
    assert result.status == "failed" and result.error.code == "history_budget_exceeded"
    assert result.error.details["required_bytes"] > 500
    assert result.count == 0 and result.items == [] and result.text == ""
    assert result.metadata["used_bytes"] == 0
    assert "private" not in result.model_dump_json()


@pytest.mark.parametrize("during", ["list", "load"])
async def test_cancellation_propagates_without_becoming_a_failure_result(during):
    started = asyncio.Event()
    cleaned = asyncio.Event()

    class BlockingArchive(ReadOnlyArchive):
        async def block(self):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        async def list(self, workflow_id=None, limit=100):
            if during == "list":
                await self.block()
            return await super().list(workflow_id, limit)

        async def load_artifact(self, session_id, name):
            await self.block()

    task = asyncio.create_task(collect(BlockingArchive([record("previous")])))
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned.is_set()


@pytest.mark.parametrize("artifact", ["collection", "analysis", "final"])
async def test_real_file_archive_integration_is_read_only(tmp_path, artifact):
    write_session(tmp_path, "previous")
    write_session(tmp_path, "older", created_at=NOW - timedelta(days=1))
    original = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*.json")}
    archive = FileArchiveReader(tmp_path, clock=lambda: NOW)
    result = await collect(archive, artifact=artifact, limit=2)
    assert result.status == "success" and result.count == 2
    assert [item["session_id"] for item in result.items] == ["previous", "older"]
    assert result.metadata["used_bytes"] == len(result.text.encode("utf-8"))
    assert {
        path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*.json")
    } == original


@pytest.mark.parametrize("reason", ["disabled", "missing", "expired", "corrupt"])
async def test_real_unavailable_history_preserves_missing_vs_corrupt(tmp_path, reason):
    envelope = write_session(tmp_path, "previous")
    if reason == "disabled":
        envelope.backup.enabled = False
    elif reason == "missing":
        (tmp_path / "sessions" / "previous" / "final.json").unlink()
    elif reason == "expired":
        envelope.record.artifacts["final"].expires_at = NOW
    else:
        (tmp_path / "sessions" / "previous" / "final.json").write_text("private corrupt body")
    save_envelope(tmp_path, envelope)
    result = await collect(FileArchiveReader(tmp_path, clock=lambda: NOW))
    assert result.status == ("failed" if reason == "corrupt" else "missing")
    assert result.error.details["reason"] == reason
    assert "private" not in result.model_dump_json()
