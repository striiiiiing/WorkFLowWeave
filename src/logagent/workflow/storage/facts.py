"""SQLModel 业务存档：保存不可变逻辑写入及独立业务版本，不决定图执行进度。"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import orjson
from pydantic import TypeAdapter
from sqlmodel import func, select

from logagent.errors import LogAgentError
from logagent.models import ID, BackupPolicy, JSONObject

from . import retention
from .database import ArchiveDatabase
from .models import (
    BODY_TABLES as _BODY_TABLES,
)
from .models import (
    TERMINAL_STATUSES as _TERMINAL,
)
from .models import (
    CheckpointSource,
    EpochRetention,
    PromptVersion,
    ResultProvenance,
    SessionEntry,
    SessionHeader,
)

_JSON = TypeAdapter(JSONObject)
_ID = TypeAdapter(ID)


def _json(value: dict) -> str:
    """校验 JSON 对象并按键排序编码，提供稳定的内容摘要输入。"""
    checked = _JSON.validate_python(value)
    return orjson.dumps(checked, option=orjson.OPT_SORT_KEYS).decode()


def _hash(value: str) -> str:
    """计算 UTF-8 文本的 SHA-256 摘要，用于完整性及幂等冲突检查。"""
    return hashlib.sha256(value.encode()).hexdigest()


class SessionStore(ArchiveDatabase):
    """以追加条目保存业务历史，事务内发布版本、摘要、正文和可用性。

    相同逻辑键重复提交复用原版本，内容冲突明确报错；正文过期后仍保留
    原摘要与幂等键，避免重放把旧正文重新插入。
    """

    def create(
        self,
        session_id: str,
        workflow_id: str,
        policy: BackupPolicy,
        *,
        workflow_name: str | None = None,
    ) -> None:
        """原子创建 session 头与 created 事件，重复创建相同绑定时直接返回。

        同一 session 已绑定不同 Workflow 或备份策略时抛出 storage_conflict。
        """
        _ID.validate_python(session_id)
        _ID.validate_python(workflow_id)
        policy_json = _json(policy.model_dump(mode="json"))
        with self._transaction() as session:
            row = session.get(SessionHeader, session_id)
            if row:
                if row.workflow_id != workflow_id or row.policy != policy_json:
                    raise LogAgentError("storage_conflict", "session 标识已绑定其他配置")
                return
            session.add(
                SessionHeader(
                    session_id=session_id,
                    workflow_id=workflow_id,
                    created_at=datetime.now(UTC).isoformat(),
                    policy=policy_json,
                )
            )
            session.flush()
            summary = {"status": "created"}
            if workflow_name is not None:
                summary["workflow_name"] = workflow_name
            self.write(session_id, "created", stage=None, scope="parent", summary=summary)

    def write(
        self,
        session_id: str,
        key: str,
        *,
        stage: str | None,
        scope: str,
        summary: dict,
        body: dict | None = None,
        availability: str = "available",
        category: str | None = None,
        source: dict | None = None,
        provenance: dict | None = None,
    ) -> dict:
        """追加业务条目并返回存档内容，同一 session 内版本递增。

        稳定 key 已存在时比较原 digest：相同内容复用原版本，不同内容报冲突。
        新版本、摘要、正文及可用性在同一事务内发布。
        """
        encoded_summary = _json(summary)
        digest = _hash(
            _json(
                {
                    "stage": stage,
                    "scope": scope,
                    "summary": summary,
                    "body": body,
                    "availability": availability,
                    "category": category,
                }
            )
        )
        with self._transaction() as session:
            previous = session.exec(
                select(SessionEntry).where(
                    SessionEntry.session_id == session_id,
                    SessionEntry.write_key == key,
                )
            ).first()
            if previous:
                if previous.digest != digest:
                    raise LogAgentError("storage_conflict", "幂等键对应的 session 内容不同")
                if source:
                    self.record_source(session_id, key, source)
                return self._entry(previous)
            if session.get(SessionHeader, session_id) is None:
                raise LogAgentError("session_not_found", "session 不存在")
            latest = session.exec(
                select(func.max(SessionEntry.version)).where(
                    SessionEntry.session_id == session_id,
                )
            ).one()
            provenance = self._prompts(session, provenance) if provenance is not None else None
            body = (
                self._prompts(session, body)
                if category == "snapshot" and body is not None
                else body
            )
            stored_body = _json(body) if body is not None else None
            row = SessionEntry(
                session_id=session_id,
                version=(latest or 0) + 1,
                write_key=key,
                stage=stage,
                scope=scope,
                summary=encoded_summary,
                body=None if category in _BODY_TABLES else stored_body,
                availability=availability,
                category=category,
                digest=digest,
                created_at=datetime.now(UTC).isoformat(),
            )
            session.add(row)
            session.flush()
            deadline = self._deadline(session, row)
            if (
                deadline is not None
                and datetime.now(UTC) >= deadline
                and availability == "available"
            ):
                row.availability, row.body = "expired", None
                session.add(row)
            elif category in _BODY_TABLES and stored_body is not None:
                session.add(
                    _BODY_TABLES[category](
                        session_id=session_id, version=row.version, content=stored_body
                    )
                )
            if provenance is not None:
                session.add(
                    ResultProvenance(
                        session_id=session_id, version=row.version, details=_json(provenance)
                    )
                )
            if source:
                self.record_source(session_id, key, source)
            epoch = summary.get("execution_epoch")
            if epoch:
                retained = session.get(EpochRetention, (session_id, epoch))
                if retained is None:
                    retained = EpochRetention(
                        session_id=session_id,
                        execution_epoch=epoch,
                        policy=session.get(SessionHeader, session_id).policy,
                    )
                if summary.get("status") in _TERMINAL and retained.anchor is None:
                    retained.anchor = row.created_at
                session.add(retained)
            session.flush()
            return self._entry(row)

    def _entry(self, row: SessionEntry, *, include_body=True) -> dict:
        """解码数据库条目并检查内容摘要；非法数据转换为 storage_corrupt。

        expired 条目正文已清除，保留的是清理前摘要，因此不再按当前正文验算。
        """
        value = row.model_dump()
        if not include_body:
            value["summary"] = orjson.loads(value["summary"])
            value["body"] = None
            return value
        if row.category in _BODY_TABLES and row.availability == "available":
            body_row = self._session.get(_BODY_TABLES[row.category], (row.session_id, row.version))
            if body_row is not None:
                value["body"] = body_row.content
            # Old archives retain their original body and expiry until explicit migration.
        try:
            value["summary"] = _JSON.validate_python(orjson.loads(value["summary"]))
            value["body"] = (
                _JSON.validate_python(orjson.loads(value["body"])) if value["body"] else None
            )
            if value["category"] == "snapshot" and value["body"] is not None:
                value["body"] = self._expand_prompts(value["body"])
            if value["availability"] != "expired":
                expected = _hash(
                    _json(
                        {
                            "stage": value["stage"],
                            "scope": value["scope"],
                            "summary": value["summary"],
                            "body": value["body"],
                            "availability": value["availability"],
                            "category": value["category"],
                        }
                    )
                )
                if expected != value["digest"]:
                    raise ValueError("Archive digest mismatch")
        except (ValueError, TypeError):
            raise LogAgentError("storage_corrupt", "session 业务存档损坏") from None
        return value

    def entry(self, session_id: str, key: str) -> dict | None:
        """按 session 和稳定业务键读取单条存档，不存在时返回 None。"""
        with self._transaction() as session:
            row = session.exec(
                select(SessionEntry).where(
                    SessionEntry.session_id == session_id,
                    SessionEntry.write_key == key,
                )
            ).first()
            return self._entry(row) if row else None

    def entries(
        self, session_id: str, version: int | None = None, *, include_body=True
    ) -> tuple[dict, list[dict]]:
        """一致读取 session 头及截至指定版本的全部条目，按版本升序返回。"""
        with self._transaction() as session:
            header = session.get(SessionHeader, session_id)
            if header is None:
                raise LogAgentError("session_not_found", "session 不存在")
            if version is not None and (type(version) is not int or version < 1):
                raise LogAgentError("invalid_argument", "session version 必须为正整数")
            statement = select(SessionEntry).where(SessionEntry.session_id == session_id)
            if version is not None:
                statement = statement.where(SessionEntry.version <= version)
            rows = session.exec(statement.order_by(SessionEntry.version)).all()
            if not rows or (version is not None and rows[-1].version != version):
                raise LogAgentError("version_not_found", "session 业务版本不存在")
            return header.model_dump(), [
                self._entry(row, include_body=include_body) for row in rows
            ]

    def session_ids(self) -> list[str]:
        """按创建时间降序列出 session ID，同一创建时间按 ID 排序。"""
        with self._transaction() as session:
            return list(
                session.exec(
                    select(SessionHeader.session_id).order_by(
                        SessionHeader.created_at.desc(),
                        SessionHeader.session_id,
                    )
                ).all()
            )

    def retention(self, sid, epoch):
        return retention.retention(self, sid, epoch)

    def checkpoint_deadline(self, sid, epoch):
        return retention.checkpoint_deadline(self, sid, epoch)

    def _deadline(self, session, row):
        return retention._deadline(self, session, row)

    def expire(self, now=None, *, active=(), session_id=None):
        return retention.expire(self, now, active=active, session_id=session_id)

    def archive_incomplete(self, sid):
        with self._transaction():
            _, entries = self.entries(sid, include_body=False)
            keys = {entry["write_key"] for entry in entries}
            return any(
                entry["scope"] == "archive_error" and entry["summary"]["result_key"] not in keys
                for entry in entries
            )

    def provenance(self, sid, version):
        with self._transaction() as session:
            row = session.get(ResultProvenance, (sid, version))
            return self._expand_prompts(orjson.loads(row.details)) if row else None

    @staticmethod
    def _prune_prompts(session):
        # Provenance survives body expiry, so upstream identities and static prompts
        # remain readable while any retained trace still references them.
        def references(value):
            if isinstance(value, list):
                return set().union(*(references(item) for item in value))
            if not isinstance(value, dict):
                return set()
            if set(value) == {"prompt_version"}:
                return {value["prompt_version"]}
            return set().union(*(references(item) for item in value.values()))

        used = set()
        for details in session.exec(select(ResultProvenance.details)).all():
            used.update(references(orjson.loads(details)))
        for body in session.exec(
            select(SessionEntry.body).where(
                SessionEntry.category == "snapshot", SessionEntry.body.is_not(None)
            )
        ).all():
            used.update(references(orjson.loads(body)))
        for row in session.exec(select(PromptVersion)).all():
            if row.digest not in used:
                session.delete(row)

    def _prompts(self, session, value):
        if isinstance(value, list):
            return [self._prompts(session, item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            if key in {"system_prompt", "input_prompt", "user_prompt"} and isinstance(item, str):
                digest = _hash(_json({"format_version": 1, "content": item}))
                if session.get(PromptVersion, digest) is None:
                    session.add(PromptVersion(digest=digest, content=item))
                    session.flush()
                result[key] = {"prompt_version": digest}
            else:
                result[key] = self._prompts(session, item)
        return result

    def _expand_prompts(self, value):
        if isinstance(value, list):
            return [self._expand_prompts(item) for item in value]
        if not isinstance(value, dict):
            return value
        if set(value) == {"prompt_version"}:
            row = self._session.get(PromptVersion, value["prompt_version"])
            if row is None:
                raise LogAgentError("storage_corrupt", "提示词版本缺失")
            return row.content
        return {key: self._expand_prompts(item) for key, item in value.items()}

    def record_source(self, sid, key, source):
        with self._transaction() as session:
            identity = (sid, key, source["checkpoint_id"], source["namespace"], source["task_id"])
            if session.get(CheckpointSource, identity) is None:
                session.add(CheckpointSource(session_id=sid, write_key=key, **source))
