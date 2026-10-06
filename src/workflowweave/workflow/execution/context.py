"""固定输入快照与能力上下文；不持有运行任务。"""

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any

from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import CollectionContext, WorkflowDefinition, WorkflowSnapshot, copy_model


async def _call(fn: Callable, *args, **kwargs):
    """调用注入的同步或异步接口，统一返回实际结果。"""
    value = fn(*args, **kwargs)
    return await value if inspect.isawaitable(value) else value


async def capture_snapshot(workflow, resources):
    """复制完整快照或按已保存 ID 生成快照，拒绝直接触发裸定义。"""
    if isinstance(workflow, WorkflowSnapshot):
        return copy_model(workflow)
    if resources is None:
        raise WorkFLowWeaveError("configuration_unavailable", "未注入资源仓库")
    if isinstance(workflow, WorkflowDefinition):
        raise WorkFLowWeaveError(
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
    agent_service: Any = None
    collection_slots: asyncio.Semaphore = field(init=False)
    analysis_slots: asyncio.Semaphore = field(init=False)
    fresh_intents: set[tuple[str, str]] = field(default_factory=set, init=False)
    _intent_barriers: dict[tuple[str, str], asyncio.Future] = field(
        default_factory=dict, init=False, repr=False
    )

    def __post_init__(self):
        # Collection and stage recovery must use this run's frozen MCP bindings.
        object.__setattr__(
            self,
            "collection",
            replace(
                self.collection,
                mcp_servers={key: copy_model(value) for key, value in self.snapshot.mcp_servers.items()},
            ),
        )
        object.__setattr__(
            self,
            "collection_slots",
            asyncio.Semaphore(self.snapshot.workflow.collection_concurrency),
        )
        object.__setattr__(
            self, "analysis_slots", asyncio.Semaphore(self.snapshot.workflow.analysis_concurrency)
        )

    def input_token_counters(self):
        """Return the counters required by every model consuming shared input."""
        processing = self.snapshot.workflow.input_processing
        limited = processing.total_tokens is not None or any(
            source.limits.item_tokens is not None or source.limits.field_tokens is not None
            for source in self.snapshot.sources.values()
        )
        if not limited:
            return ()
        factory = getattr(self.ai_service, "input_counter", None)
        if not callable(factory):
            raise WorkFLowWeaveError("tokenizer_unavailable", "消费输入的 AI 服务未提供 tokenizer")
        models = []
        seen = set()
        for task in self.snapshot.workflow.analyses:
            key = (task.ai, task.model)
            if key not in seen:
                seen.add(key)
                models.append(key)
        fan = self.snapshot.workflow.fan_in
        if fan is not None and "$input" in fan.ordered_inputs(self.snapshot.workflow.analyses):
            if fan.ai is not None:
                key = (fan.ai, fan.model)
            else:
                reused = fan.reused_task(self.snapshot.workflow.analyses)
                key = (reused.ai, reused.model) if reused is not None else None
            if key is not None and key not in seen:
                seen.add(key)
                models.append(key)
        return tuple(factory(self.snapshot.ai[ai_id], model) for ai_id, model in models)

    def register_intent(self, execution_epoch: str, key: str) -> None:
        """Register a fresh intent before its checkpoint is emitted."""
        identity = (execution_epoch, key)
        self.fresh_intents.add(identity)
        if identity not in self._intent_barriers:
            self._intent_barriers[identity] = asyncio.get_running_loop().create_future()

    async def wait_for_intent(self, execution_epoch: str, key: str) -> None:
        """Wait until the stream consumer has archived the intent checkpoint."""
        identity = (execution_epoch, key)
        if identity not in self.fresh_intents:
            return
        barrier = self._intent_barriers.get(identity)
        if barrier is None:
            raise RuntimeError("intent checkpoint barrier was not registered")
        await barrier

    def confirm_intent(self, execution_epoch: str, key: str) -> None:
        """Release receipt execution after durable intent fact creation."""
        barrier = self._intent_barriers.get((execution_epoch, key))
        if barrier is not None and not barrier.done():
            barrier.set_result(None)

    def abort_intents(self, error: BaseException) -> None:
        """Unblock pending receipts when the single event stream fails."""
        for barrier in self._intent_barriers.values():
            if barrier.done():
                continue
            if isinstance(error, asyncio.CancelledError):
                barrier.cancel()
            else:
                barrier.set_exception(error)
                # A sibling may fail before this receipt reaches the await. Mark
                # the exception as observed while preserving it for a waiter.
                barrier.exception()
