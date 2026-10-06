"""Independent content retention and prompt provenance in the real SQLite store."""

from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from workflowweave.models import BackupPolicy
from workflowweave.workflow.storage.facts import SessionStore
from workflowweave.workflow.storage.models import AnalysisBody, CollectionBody, PromptVersion, ReportBody
from workflowweave.workflow.storage.sessions import SessionView
from workflowweave.workflow.stream.subscriptions.checkpoints import CheckpointArchive


@pytest.mark.parametrize("days", [
    (1, 3, 2), (3, 1, 2), (2, 2, 2), (2, 3, 1),
])
def test_independent_body_tables_and_arbitrary_retention_order(tmp_path, days):
    store = SessionStore(tmp_path / "sessions.sqlite3")
    try:
        policy = BackupPolicy(collection_retention_days=days[0],
                              analysis_retention_days=days[1], final_retention_days=days[2])
        store.create("s", "w", policy)
        versions = {}
        for category, scope in (("collection", "collect"), ("analysis", "analyze"),
                                ("final", "output")):
            versions[category] = store.write("s", category, stage="aggregate", scope=scope,
                summary={"execution_epoch": "epoch", "output_id": "final", "item_id": category,
                         "item_status": "success"},
                body={"text": category}, category=category)["version"]
        store.write("s", "finish", stage="finish", scope="phase",
                    summary={"execution_epoch": "epoch", "status": "completed"})
        with store._transaction() as db:
            for category, model in (("collection", CollectionBody), ("analysis", AnalysisBody),
                                    ("final", ReportBody)):
                rows = db.exec(select(model)).all()
                assert [(row.version, row.content) for row in rows] == [
                    (versions[category], f'{{"text":"{category}"}}')]
        anchor = datetime.fromisoformat(store.retention("s", "epoch")["anchor"])
        for elapsed in range(1, 4):
            store.expire(anchor + timedelta(days=elapsed, seconds=1))
            for category, duration in zip(("collection", "analysis", "final"), days, strict=True):
                entry = store.entry("s", category)
                assert entry["version"] == versions[category]
                assert entry["availability"] == ("expired" if duration <= elapsed else "available")
        assert store.entry("s", "finish")["availability"] == "available"
    finally:
        store.close()


def test_same_epoch_replay_cannot_extend_deadline_or_revive_expired_body(tmp_path):
    store = SessionStore(tmp_path / "sessions.sqlite3")
    try:
        store.create("s", "w", BackupPolicy(collection_retention_days=1))
        summary = {"execution_epoch": "epoch", "item_id": "source", "item_status": "success"}
        original = store.write("s", "source", stage="collect", scope="collect",
                               summary=summary, body={"text": "old"}, category="collection")
        store.write("s", "terminal", stage="finish", scope="phase",
                    summary={"execution_epoch": "epoch", "status": "completed"})
        anchor = store.retention("s", "epoch")["anchor"]
        store.expire(datetime.fromisoformat(anchor) + timedelta(days=2))
        replay = store.write("s", "source", stage="collect", scope="collect",
                             summary=summary, body={"text": "old"}, category="collection")
        assert replay["version"] == original["version"]
        assert replay["availability"] == "expired" and replay["body"] is None
        assert store.retention("s", "epoch")["anchor"] == anchor
        with store._transaction() as db:
            assert db.exec(select(CollectionBody)).all() == []
    finally:
        store.close()


async def test_prompt_versions_dedupe_across_sessions_and_snapshot_off_has_no_prompt(tmp_path):
    store = SessionStore(tmp_path / "sessions.sqlite3")
    try:
        details = {"prompts": {"system_prompt": "shared system", "input_prompt": "{input}"}}
        for sid in ("first", "second"):
            store.create(sid, "w", BackupPolicy())
            store.write(sid, "analysis", stage="analyze", scope="analyze",
                        summary={"execution_epoch": "epoch", "item_id": "task", "item_status": "success"},
                        body={"text": sid}, category="analysis", provenance=details)
        with store._transaction() as db:
            assert len(db.exec(select(PromptVersion)).all()) == 2
        for sid in ("first", "second"):
            assert store.provenance(sid, 2)["prompts"]["system_prompt"] == "shared system"
        store.create("disabled", "w", BackupPolicy(snapshot=False))
        async def publish(record):
            pass
        archive = CheckpointArchive(None, store, SessionView(store), publish)
        await archive._write("disabled", "snapshot", None, "configuration", "snapshot",
                             BackupPolicy(snapshot=False), {},
                             {"snapshot": {"system_prompt": "private disabled prompt"}}, None)
        assert store.entry("disabled", "snapshot")["availability"] == "not_saved"
        assert store.entry("disabled", "snapshot")["body"] is None
        with store._transaction() as db:
            assert len(db.exec(select(PromptVersion)).all()) == 2
    finally:
        store.close()


async def test_report_is_readable_after_upstream_expiry(tmp_path):
    store = SessionStore(tmp_path / "sessions.sqlite3")
    try:
        store.create("s", "w", BackupPolicy(collection_retention_days=1))
        store.write("s", "source", stage="collect", scope="collect",
                    summary={"execution_epoch": "epoch", "item_id": "source", "item_status": "success"},
                    body={"text": "upstream"}, category="collection")
        store.write("s", "phase:collect", stage="collect", scope="phase",
                    summary={"execution_epoch": "epoch", "status": "running"})
        store.write("s", "report", stage="aggregate", scope="output",
                    summary={"execution_epoch": "epoch", "output_id": "final"},
                    body={"text": "retained report"}, category="final")
        store.write("s", "phase:aggregate", stage="aggregate", scope="phase",
                    summary={"execution_epoch": "epoch", "status": "running"})
        store.write("s", "terminal", stage="finish", scope="phase",
                    summary={"execution_epoch": "epoch", "status": "completed"})
        store.expire(datetime.fromisoformat(store.retention("s", "epoch")["anchor"]) + timedelta(days=2))
        view = SessionView(store)
        version = (await view.get_session("s")).version
        assert (await view.get_phase_content("s", "collect", version=version)).availability == "expired"
        report = await view.get_phase_content("s", "aggregate", version=version)
        assert report.availability == "available"
        assert report.content["outputs"] == {"final": "retained report"}
    finally:
        store.close()
