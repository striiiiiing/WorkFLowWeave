"""官方 SQLite saver 的窄 namespace 清理适配及有界后台任务。"""

from __future__ import annotations

import asyncio
import logging

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

logger = logging.getLogger("logagent.workflow.checkpoints")
# 合并每个 session 的请求；容量由运行准入上限传入，不增加独立并发默认。


class CheckpointNamespaces:
    def __init__(self, saver: AsyncSqliteSaver):
        self.saver = saver

    async def completed(self, session_id):
        """只返回父图 loop 后继已提交相同结果引用的真实 invocation namespace。"""
        from logagent.workflow.graph import GRAPH_REVISION

        config = {"configurable": {"thread_id": session_id}}
        saved = [item async for item in self.saver.alist(config)]
        roots = [item for item in saved if not item.config["configurable"]["checkpoint_ns"]]
        successors = {}
        for parent in roots:
            if not parent.parent_config or parent.metadata.get("source") != "loop":
                continue
            values = parent.checkpoint.get("channel_values", {})
            if values.get("graph_revision") != GRAPH_REVISION:
                continue
            predecessor = parent.parent_config["configurable"]["checkpoint_id"]
            successors.setdefault(predecessor, []).append(values)
        latest = {}
        ids = {}
        for item in saved:
            namespace = item.config["configurable"]["checkpoint_ns"]
            if namespace:
                latest.setdefault(namespace, item)
                ids.setdefault(namespace, set()).add(item.config["configurable"]["checkpoint_id"])
        candidates = set()
        for namespace, item in latest.items():
            stage = namespace.split(":", 1)[0]
            if stage not in {"collect", "analyze", "notify"} or "|" in namespace:
                continue
            values = item.checkpoint.get("channel_values", {})
            ref = values.get("phases", {}).get(stage)
            origin = item.metadata.get("parents", {}).get("")
            if ref and any(
                parent.get("execution_epoch") == values.get("execution_epoch")
                and parent.get("phases", {}).get(stage) == ref
                for parent in successors.get(origin, ())
            ):
                candidates.add(namespace)
        # 嵌套归属由 saver 提供的 parents 映射证明；不拼接或模糊匹配 namespace。
        changed = True
        while changed:
            changed = False
            for namespace, item in latest.items():
                if namespace in candidates:
                    continue
                if any(parent in candidates and checkpoint in ids[parent]
                       for parent, checkpoint in item.metadata.get("parents", {}).items()):
                    candidates.add(namespace)
                    changed = True
        return candidates

    async def delete(self, session_id, namespaces):
        """复用 saver 连接互斥，原子删除该 invocation 的 checkpoint 和 pending writes。"""
        names = sorted(set(namespaces))
        if any(not name for name in names):
            raise ValueError("parent checkpoint namespace cannot be deleted")
        if not names:
            return
        await self.saver.setup()
        async with self.saver.lock, self.saver.conn.cursor() as cursor:
            await cursor.execute("BEGIN IMMEDIATE")
            try:
                for name in names:
                    await cursor.execute(
                        "DELETE FROM writes WHERE thread_id = ? AND checkpoint_ns = ?",
                        (session_id, name),
                    )
                    await cursor.execute(
                        "DELETE FROM checkpoints WHERE thread_id = ? AND checkpoint_ns = ?",
                        (session_id, name),
                    )
                await self.saver.conn.commit()
            except BaseException:
                await self.saver.conn.rollback()
                raise


class CheckpointCleanup:
    """一个生命周期任务，按 session 合并请求，失败保留数据供下次补扫。"""

    def __init__(self, saver, admission_lock, *, capacity):
        self.storage = CheckpointNamespaces(saver)
        self.lock = admission_lock
        self.queue = asyncio.Queue(maxsize=capacity)
        self.pending = set()
        self.accepting = True
        self.task = asyncio.create_task(self._run(), name="workflow-checkpoint-cleanup")

    async def request(self, session_id):
        if not self.accepting or session_id in self.pending:
            return
        self.pending.add(session_id)
        try:
            await self.queue.put(session_id)
        except BaseException:
            self.pending.discard(session_id)
            raise

    async def _run(self):
        while True:
            session_id = await self.queue.get()
            try:
                if session_id is None:
                    return
                self.pending.discard(session_id)
                async with self.lock:
                    namespaces = await self.storage.completed(session_id)
                    await self.storage.delete(session_id, namespaces)
            except Exception:
                logger.exception("子图 checkpoint 清理失败，保留数据等待再次核对",
                                 extra={"session_id": session_id})
            finally:
                self.queue.task_done()

    async def close(self):
        self.accepting = False
        # 关闭不能无限等待数据库；只取消清理任务，不报告未完成删除成功。
        try:
            async with asyncio.timeout(10):
                await self.queue.join()
                await self.queue.put(None)
                await self.task
        except TimeoutError:
            logger.error("子图 checkpoint 清理收尾超时，未处理数据将在下次启动核对")
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
