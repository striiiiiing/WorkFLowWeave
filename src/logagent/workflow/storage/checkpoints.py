"""官方 SQLite saver 接入与 namespace 查询、清理。"""

from __future__ import annotations

import asyncio
import logging

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

logger = logging.getLogger("logagent.workflow.storage.checkpoints")


async def finish_write(operation):
    """SQLite's worker keeps executing SQL after coroutine cancellation.

    Keep the saver lock until its commit has finished, then propagate cancellation.
    This prevents an abandoned transaction from blocking the archive connection.
    """
    task = asyncio.create_task(operation)
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


class WorkflowSqliteSaver(AsyncSqliteSaver):
    async def aput(self, config, checkpoint, metadata, new_versions):
        return await finish_write(super().aput(config, checkpoint, metadata, new_versions))

    async def aput_writes(self, config, writes, task_id, task_path=""):
        return await finish_write(super().aput_writes(config, writes, task_id, task_path))

    async def adelete_thread(self, thread_id):
        return await finish_write(super().adelete_thread(thread_id))


class CheckpointNamespaces:
    def __init__(self, saver: AsyncSqliteSaver, store=None):
        self.saver, self.store = saver, store

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
