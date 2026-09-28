"""应用运行任务的唯一持有者；不承担图内节点调度。"""

import asyncio
from collections import OrderedDict

from logagent.errors import LogAgentError


class RunCoordinator:
    """管理进程内运行任务、容量与取消，不承担持久历史查询。

    最近 32 个完成任务保留为有限等待窗口，包含运行异常；
    长期业务历史由 SessionStore 保存，避免任务正文在内存中无界积累。
    """

    COMPLETED_LIMIT = 32

    def __init__(self, *, max_concurrent_runs=4):
        """初始化任务集合和准入状态；并发容量必须为正整数。"""
        if type(max_concurrent_runs) is not int or max_concurrent_runs < 1:
            raise ValueError("max_concurrent_runs must be positive")
        self._max = max_concurrent_runs
        self._tasks: dict[str, asyncio.Task] = {}
        self._completed: OrderedDict[str, asyncio.Task] = OrderedDict()
        self._started: dict[str, asyncio.Event] = {}
        self.accepting = True

    @property
    def active(self):
        """返回仍在活动任务集合中的运行数量。"""
        return len(self._tasks)

    def contains(self, sid):
        """判断指定 session 是否仍由活动任务集合持有。"""
        return sid in self._tasks

    def check(self, sid):
        """检查准入开关、同 session 互斥和全局容量，拒绝时抛出业务错误。"""
        if not self.accepting:
            raise LogAgentError("not_ready", "Workflow 未开放运行准入")
        if sid in self._tasks:
            raise LogAgentError("session_active", "同一 session 已在运行")
        if self.active >= self._max:
            raise LogAgentError("capacity_exhausted", "运行容量已满")

    def submit(self, sid, operation):
        """创建并持有后台任务；完成后移入有界等待窗口。"""
        self.check(sid)
        started = self._started[sid] = asyncio.Event()

        async def run():
            """标记协程已启动，再进入实际运行的异常处理边界。"""
            started.set()
            return await operation()

        def done(task):
            """清理活动句柄并取出异常，避免无人等待的任务异常丢失诊断。"""
            self._tasks.pop(sid, None)
            self._started.pop(sid, None)
            if not task.cancelled():
                task.exception()
            self._completed[sid] = task
            while len(self._completed) > self.COMPLETED_LIMIT:
                self._completed.popitem(last=False)

        self._completed.pop(sid, None)
        task = asyncio.create_task(run(), name=f"workflow:{sid}")
        self._tasks[sid] = task
        task.add_done_callback(done)

    async def wait(self, sid):
        """等待活动或近期完成任务；调用者取消等待不会取消后台运行。

        结果离开内存窗口后抛出 session_not_active，应改用 session 查询。
        """
        task = self._tasks.get(sid) or self._completed.get(sid)
        if task is None:
            raise LogAgentError("session_not_active", "运行结果已离开内存等待窗口，请查询 session")
        return await asyncio.shield(task)

    async def cancel(self, sid):
        """请求取消活动任务，返回是否发出了取消请求。

        先等待任务启动，使其有机会进入异常处理边界并记录取消事件；
        返回 True 不代表任务已结束，结束结果由 wait 获取。
        """
        task = self._tasks.get(sid)
        if task is None or task.done():
            return False
        await self._started[sid].wait()
        task.cancel()
        return True

    async def shutdown(self):
        """关闭准入，取消全部活动任务并等待它们收尾。"""
        self.accepting = False
        tasks = list(self._tasks.values())
        for sid in list(self._tasks):
            await self.cancel(sid)
        await asyncio.gather(*tasks, return_exceptions=True)
