"""固定输入快照与能力上下文；不持有运行任务。"""

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from logagent.errors import LogAgentError
from logagent.models import CollectionContext, WorkflowDefinition, WorkflowSnapshot, copy_model


async def _call(fn: Callable, *args, **kwargs):
    """调用注入的同步或异步接口，统一返回实际结果。"""
    value = fn(*args, **kwargs)
    return await value if inspect.isawaitable(value) else value


async def capture_snapshot(workflow, resources):
    """复制完整快照或按已保存 ID 生成快照，拒绝直接触发裸定义。"""
    if isinstance(workflow, WorkflowSnapshot):
        return copy_model(workflow)
    if resources is None:
        raise LogAgentError("configuration_unavailable", "未注入资源仓库")
    if isinstance(workflow, WorkflowDefinition):
        raise LogAgentError(
            "invalid_argument", "触发需要已保存的 Workflow ID 或完整 WorkflowSnapshot"
        )
    return copy_model(await _call(resources.snapshot, workflow))


@dataclass(frozen=True)
class WorkflowContext:
    """每次执行的依赖；snapshot 由父图持久化配置派生，不独立保存。"""

    snapshot: WorkflowSnapshot
    collection: CollectionContext
    collector_manager: Any
    ai_service: Any
    channel_manager: Any
    finalize: Callable[[str], Awaitable[None]]
    collection_slots: asyncio.Semaphore = field(init=False)
    analysis_slots: asyncio.Semaphore = field(init=False)
    fresh_intents: set[tuple[str, str]] = field(default_factory=set, init=False)

    def __post_init__(self):
        object.__setattr__(
            self,
            "collection_slots",
            asyncio.Semaphore(self.snapshot.workflow.collection_concurrency),
        )
        object.__setattr__(
            self, "analysis_slots", asyncio.Semaphore(self.snapshot.workflow.analysis_concurrency)
        )
