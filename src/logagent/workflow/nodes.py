"""One archive-node factory shared by parent stages and child work items."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable
from copy import deepcopy

from logagent.errors import LogAgentError


async def _commit(function, *args, **kwargs):
    # Cancelling a wrapper cannot terminate a SQLite operation in a worker thread.
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        task.result()
        raise


class ArchiveRuntime:
    """Invocation-only bodies supplement persisted archives when backup is disabled."""

    def __init__(self, store, session_id, policy):
        self.store, self.session_id, self.policy = store, session_id, policy
        self._bodies: dict[str, dict] = {}

    async def read(self, key: str) -> dict:
        if key in self._bodies:
            return deepcopy(self._bodies[key])
        entry = await asyncio.to_thread(self.store.entry, self.session_id, key)
        if entry is None or entry["availability"] != "available" or entry["body"] is None:
            raise LogAgentError(
                "recovery_unavailable", "原 session 内容不可用",
                {"key": key, "reason": entry["availability"] if entry else "missing"},
            )
        return entry["body"]

    async def save(self, key, *, stage, scope, summary, body=None, category=None):
        persist = category is None or (
            self.policy.enabled and getattr(self.policy, category)
        )
        if body is not None:
            self._bodies[key] = deepcopy(body)
        try:
            return await _commit(
                self.store.write, self.session_id, key, stage=stage, scope=scope,
                summary=summary, body=body if persist else None, category=category,
                availability="available" if persist else "not_saved",
            )
        except (sqlite3.Error, OSError):
            if body is None or category is None:
                raise
            result = await _commit(
                self.store.write, self.session_id, key, stage=stage, scope=scope,
                summary={**summary, "backup_failed": True}, availability="write_failed", category=category,
            )
            if self.policy.on_failure == "stop":
                raise LogAgentError("backup_failed", "正文保存失败，备份策略要求停止") from None
            return result


def archive_node(
    runtime: ArchiveRuntime, *, scope: str, stage: str | None,
    key: str | Callable, operation: Callable, category: str | None,
    summarize: Callable = lambda body: {},
    publish: Callable = lambda ident, summary: {"ref": ident},
):
    """Bind the varying selectors once; replay returns the original archive reference."""
    async def node(state):
        ident = key(state) if callable(key) else key
        previous = await asyncio.to_thread(runtime.store.entry, runtime.session_id, ident)
        if previous is None:
            body = await operation(state)
            previous = await runtime.save(
                ident, stage=stage, scope=scope, summary=summarize(body),
                body=body, category=category,
            )
        if previous["availability"] == "write_failed" and runtime.policy.on_failure == "stop":
            raise LogAgentError("backup_failed", "原正文保存失败，备份策略要求停止")
        return publish(ident, previous["summary"])

    return node
