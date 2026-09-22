"""Agent defaults and their validation, shared by tools and management APIs."""

from typing import Annotated, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from logagent.models import ID, Seconds, StrictModel

PositiveInt = Annotated[int, Field(strict=True, gt=0)]
Ratio = Annotated[float, Field(gt=0, lt=1, allow_inf_nan=False)]


class SandboxConfig(StrictModel):
    enabled: bool = True
    network: bool = False


class AgentConfig(StrictModel):
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    timezone: str = "UTC"
    # 200k is the documented project default; callers may set None only when
    # they intentionally disable model execution pending an explicit limit.
    context_window: PositiveInt | None = 200_000
    output_tokens: PositiveInt = 4096
    summary_ai: ID | None = None
    summary_context_window: PositiveInt | None = None
    safety_ratio: Ratio = 0.05
    trigger_ratio: Ratio = 0.8
    keep_ratio: Ratio = 0.2
    summary_ratio: Ratio = 0.05
    summary_max_tokens: PositiveInt = 4096
    summary_prompt: str = (
        "请保留当前目标、明确约束、已确认事实、文件引用、已完成或结果未知的副作用、"
        "未完成事项和下一步；不要搬运完整工具正文。"
    )
    idle_timeout: Seconds = 300
    read_concurrency: PositiveInt = 4
    read_lines: PositiveInt = 200
    grep_matches: PositiveInt = 50
    plugin_page_size: PositiveInt = 20
    shell_timeout: Seconds = 60
    preview_tokens: PositiveInt = 2000
    output_bytes: PositiveInt = 16 * 1024 * 1024

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("必须为有效的 IANA 时区名称") from None
        return value

    @model_validator(mode="after")
    def valid_budget(self) -> Self:
        if self.keep_ratio + self.summary_ratio >= self.trigger_ratio:
            raise ValueError("保留和摘要比例之和必须低于触发比例")
        if self.context_window is not None:
            if self.output_tokens >= self.context_window * (1 - self.safety_ratio):
                raise ValueError("模型容量扣除输出与安全余量后必须有剩余空间")
        return self
