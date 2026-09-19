"""Single-source execution over an injected, read-only registry view."""

from __future__ import annotations

import asyncio
import inspect
from copy import deepcopy

from pydantic import TypeAdapter, ValidationError

from logagent.errors import LogAgentError, exception_error, validation_error
from logagent.models import (
    ID,
    CapabilityDescription,
    CollectionContext,
    CollectionResult,
    CollectorOutput,
    ErrorInfo,
    SourceConfig,
    copy_model,
)
from logagent.protocols import Collector, CollectorRegistryView
from logagent.schema import validate_instance

_ID = TypeAdapter(ID)


class CollectorManager:
    """Return collection facts; cross-source ordering and policy belong to Workflow.

    ``validate`` accepts effective sources whose Setter templates were expanded
    by configuration. ``collect`` never reads mutable plugin defaults/templates.
    """

    def __init__(self, collector_register: CollectorRegistryView) -> None:
        self._register = collector_register

    def reload_register(self, collector_register: CollectorRegistryView) -> None:
        """Install one atomically published registry view for future calls."""
        self._register = collector_register

    def describe(self) -> list[CapabilityDescription]:
        return [copy_model(description) for description in self._register.describe()]

    @staticmethod
    def _copy_source(source: SourceConfig) -> SourceConfig:
        if not isinstance(source, SourceConfig):
            raise LogAgentError("invalid_config", "来源必须是 SourceConfig")
        try:
            return copy_model(source)
        except ValidationError as exc:
            raise validation_error(exc) from None

    def _missing(self, source: SourceConfig) -> ErrorInfo:
        diagnostics = getattr(self._register, "diagnostics", None)
        errors = diagnostics(source.collector) if diagnostics is not None else []
        return ErrorInfo(
            code="collector_missing",
            message="来源引用的 Collector 未注册或加载失败",
            details={
                "collector": source.collector,
                "discovery_errors": [error.model_dump(mode="json") for error in errors],
            },
        )

    @staticmethod
    def _validate_parameters(collector: Collector, source: SourceConfig) -> None:
        if source.template is not None:
            raise LogAgentError(
                "unresolved_template",
                "来源的 Setter 模板需要先由配置模块展开",
                {"errors": [{"path": ["template"], "reason": "unresolved_template"}]},
            )
        validate_instance(source.options, collector.options_schema, path=["options"])
        validate_instance(source.setters, collector.setters_schema, path=["setters"])
        semantic_validate = getattr(collector, "validate", None)
        if semantic_validate is not None:
            if not callable(semantic_validate) or inspect.iscoroutinefunction(semantic_validate):
                raise LogAgentError("invalid_declaration", "Collector.validate 必须是同步纯函数")
            try:
                result = semantic_validate(deepcopy(source.options), deepcopy(source.setters))
                if inspect.iscoroutine(result):
                    result.close()
                if result is not None:
                    raise LogAgentError("invalid_declaration", "Collector.validate 必须返回 None")
            except Exception as exc:
                # A plugin can raise our exception type too; its message/details
                # remain arbitrary plugin text and cannot bypass this boundary.
                raise LogAgentError(
                    "invalid_config",
                    "来源选项或 Setter 未通过 Collector 语义校验",
                    {"exception_type": type(exc).__name__},
                ) from None

    def validate(self, source: SourceConfig) -> None:
        source = self._copy_source(source)
        collector = self._register.get(source.collector)
        if collector is None:
            error = self._missing(source)
            raise LogAgentError(error.code, error.message, error.details)
        self._validate_parameters(collector, source)

    async def collect(self, source: SourceConfig, context: CollectionContext) -> CollectionResult:
        loop = asyncio.get_running_loop()
        started = loop.time()
        if not isinstance(source, SourceConfig) or not isinstance(context, CollectionContext):
            raise LogAgentError("invalid_argument", "采集调用需要来源配置与运行上下文")
        try:
            source_id = _ID.validate_python(source.id)
        except ValidationError:
            raise LogAgentError("invalid_argument", "来源实例 ID 无效") from None
        try:
            source = self._copy_source(source)
        except LogAgentError as exc:
            return CollectionResult(source_id=source_id, status="failed", error=exc.info)

        collector = self._register.get(source.collector)
        if collector is None:
            return CollectionResult(
                source_id=source_id, status="missing", error=self._missing(source)
            )

        deadline = started + source.timeout
        timeout = asyncio.timeout_at(deadline)
        task = asyncio.current_task()
        initial_cancelling = task.cancelling() if task is not None else 0

        def checkpoint() -> None:
            # Inside the scope one pending cancellation may belong to its timer.
            own_cancellation = int(timeout.expired())
            if task is not None and task.cancelling() > initial_cancelling + own_cancellation:
                raise asyncio.CancelledError
            if timeout.expired() or loop.time() >= deadline:
                raise TimeoutError

        failure: Exception | None = None
        result: CollectionResult | None = None
        try:
            async with timeout:
                self._validate_parameters(collector, source)
                checkpoint()
                try:
                    raw = await collector.collect(
                        deepcopy(source.options), deepcopy(source.setters), context
                    )
                except Exception as exc:
                    # Structured error *returns* follow the Collector contract;
                    # thrown exceptions, including LogAgentError, are private.
                    raise LogAgentError(
                        "collection_failed",
                        "来源执行失败",
                        {"exception_type": type(exc).__name__},
                    ) from None
                checkpoint()
                try:
                    # Revalidate instances too: plugins may use model_construct,
                    # mutate nested data, or return a reused mutable result object.
                    data = (
                        raw.model_dump(mode="python", warnings=False)
                        if isinstance(raw, CollectorOutput)
                        else raw
                    )
                    output = CollectorOutput.model_validate(data)
                    result = CollectionResult(
                        source_id=source_id, **output.model_dump(mode="python")
                    )
                except ValidationError as exc:
                    raise validation_error(exc, code="invalid_collector_output") from None
                checkpoint()
        except asyncio.CancelledError:
            # Never invent CollectionStatus.cancelled or consume caller cancellation.
            raise
        except Exception as exc:
            failure = exc

        # __aexit__ has removed the timer's own cancellation by this point.
        # A swallowed caller cancellation or cleanup error cannot become success,
        # nor can a cleanup error overwrite an exhausted collection deadline.
        if task is not None and task.cancelling() > initial_cancelling:
            raise asyncio.CancelledError
        if timeout.expired() or loop.time() >= deadline:
            return CollectionResult(
                source_id=source_id,
                status="timeout",
                error=ErrorInfo(code="collection_timeout", message="来源整体采集时限已耗尽"),
            )
        if failure is not None:
            error = (
                failure.info
                if isinstance(failure, LogAgentError)
                else exception_error(failure, code="collection_failed", message="来源执行失败")
            )
            return CollectionResult(source_id=source_id, status="failed", error=error)
        assert result is not None
        return result
