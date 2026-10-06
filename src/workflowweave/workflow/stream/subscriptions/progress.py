"""消费本次图更新并发布已提交的业务引用；订阅者不持有执行器。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

# 每个观察者只保留有限业务更新；满队列显式要求重连，不丢事件后假装同步。
SUBSCRIBER_CAPACITY = 64


class ProgressHub:
    """仅有界传输，不维护第二份业务状态或持久化日志。"""

    def __init__(self, *, capacity=SUBSCRIBER_CAPACITY):
        self.capacity = capacity
        self.subscribers = {}

    @asynccontextmanager
    async def subscribe(self, session_id):
        queue = asyncio.Queue(maxsize=self.capacity)
        group = self.subscribers.setdefault(session_id, set())
        group.add(queue)
        try:
            yield queue
        finally:
            group.discard(queue)
            if not group:
                self.subscribers.pop(session_id, None)

    async def publish(self, event):
        for queue in tuple(self.subscribers.get(event.session_id, ())):
            if queue.full():
                # 清空只为了放入明确的失同步信号；此连接不再接收业务更新。
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)
                self.subscribers[event.session_id].discard(queue)
            else:
                queue.put_nowait(event)

    async def close(self):
        for group in self.subscribers.values():
            for queue in group:
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)
        self.subscribers.clear()
