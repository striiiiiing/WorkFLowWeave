"""运行结束和启动时的存储维护生命周期。"""

import asyncio
import logging

from workflowweave.workflow.storage.checkpoints import CheckpointNamespaces

logger = logging.getLogger(__name__)


class CheckpointCleanup:
    """defer 负责子图交接；后台任务仅检查保留期和长期正文过期。"""

    def __init__(self, saver, session_lock, *, capacity, archive, store, active, publish):
        self.storage = CheckpointNamespaces(saver, store)
        self.session_lock = session_lock
        self.archive, self.store, self.active, self.publish = archive, store, active, publish
        self.queue = asyncio.Queue(maxsize=capacity)
        self.pending = set()
        self.completions = {}
        self.accepting = True
        self.task = asyncio.create_task(self._run(), name="workflow-checkpoint-cleanup")

    async def request(self, session_id, *, completion=None):
        if completion is not None:
            self.completions[session_id] = completion
        if not self.accepting or session_id in self.pending:
            return
        self.pending.add(session_id)
        try:
            await self.queue.put(session_id)
        except BaseException:
            self.pending.discard(session_id)
            raise

    async def finalize(self, session_id):
        """由 defer 节点调用；先交接全部事实，再清理本 thread 的子图。"""
        await self.archive.reconcile(session_id)
        if await asyncio.to_thread(self.store.archive_incomplete, session_id):
            logger.error("归档未完成，保留全部子图 checkpoint", extra={"session_id": session_id})
            return
        config = {"configurable": {"thread_id": session_id}}
        namespaces = {
            item.config["configurable"]["checkpoint_ns"]
            async for item in self.storage.saver.alist(config)
            if item.config["configurable"].get("checkpoint_ns")
        }
        await self.storage.delete(session_id, namespaces)

    async def _run(self):
        while True:
            session_id = await self.queue.get()
            try:
                if session_id is None:
                    return
                self.pending.discard(session_id)
                completion = self.completions.pop(session_id, None)
                if completion is not None:
                    await asyncio.wait({completion})
                async with self.session_lock(session_id):
                    # Resume admission uses this same per-session lock. Active tasks own dependencies.
                    if self.active(session_id):
                        continue
                    await self.archive.reconcile(session_id)
                    from datetime import UTC, datetime

                    config = {"configurable": {"thread_id": session_id}}
                    saved = [item async for item in self.storage.saver.alist(config)]
                    epochs = {
                        item.checkpoint.get("channel_values", {}).get("execution_epoch")
                        for item in saved
                    }
                    deadlines = [
                        await asyncio.to_thread(self.store.checkpoint_deadline, session_id, epoch)
                        for epoch in epochs
                        if epoch
                    ]
                    incomplete = await asyncio.to_thread(self.store.archive_incomplete, session_id)
                    if (
                        not incomplete
                        and deadlines
                        and all(
                            deadline is not None and deadline <= datetime.now(UTC)
                            for deadline in deadlines
                        )
                    ):
                        # Public full-thread deletion retains no fragile partial parent dependency graph.
                        await self.storage.saver.adelete_thread(session_id)
                    if await asyncio.to_thread(self.store.expire, session_id=session_id):
                        await self.publish(await self.archive.view.get_session(session_id))
            except Exception:
                logger.exception(
                    "子图 checkpoint 清理失败，保留数据等待再次核对",
                    extra={"session_id": session_id},
                )
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
