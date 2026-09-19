"""父图和子图共用的业务存档节点：以闭包绑定身份、策略及状态发布方式。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from copy import deepcopy

from sqlalchemy.exc import DBAPIError

from logagent.errors import LogAgentError


async def _commit(function, *args, **kwargs):
    """在线程中提交业务事务，取消时也等待提交结束后再传播取消。

    asyncio 取消无法终止已经运行的 SQLite 线程；等待它结束，避免后台
    写入尚未完成就进入资源关闭或后续恢复判断。提交异常继续向上传播。
    """
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
    """持有一次执行的正文缓存及业务存档访问能力。

    关闭某类正文备份时，当前执行仍可从内存读取；进程重启后不能依赖该缓存。
    """

    def __init__(self, store, session_id, policy):
        """绑定业务存储、session 和备份策略，创建仅本次执行使用的缓存。"""
        self.store, self.session_id, self.policy = store, session_id, policy
        self._bodies: dict[str, dict] = {}

    async def read(self, key: str) -> dict:
        """优先返回缓存副本，否则读取持久正文；缺失或不可用时明确报错。"""
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
        """缓存正文，并按备份策略提交正文或未保存标记。

        category 为 None 的管理记录始终持久化。正文写入遇到 SQLite 或 I/O
        错误时先尝试记录 write_failed，再按 on_failure 停止或继续；
        管理事实无法写入时直接抛错，不能继续无法记账的外部操作。
        """
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
        except (DBAPIError, OSError):
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
    """生成父图与子图共用的幂等存档闭包。

    key 可以是固定业务键或从状态计算键的函数；operation 产生正文，
    summarize 提取摘要，publish 将存档身份及摘要映射为图状态更新。
    已有条目直接复用；新条目必须等待业务提交完成后才发布控制状态。
    """
    async def node(state):
        """读取或创建稳定键对应的存档，并在备份停止策略允许时发布引用。"""
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
