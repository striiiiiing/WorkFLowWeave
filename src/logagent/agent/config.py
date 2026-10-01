"""Agent defaults and their validation, shared by tools and management APIs."""

import os
from pathlib import Path
from typing import Annotated, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from logagent.models import ID, Seconds, StrictModel

PositiveInt = Annotated[int, Field(strict=True, gt=0)]


class SandboxConfig(StrictModel):
    enabled: bool = True
    network: bool = False


def local_timezone() -> str:
    if os.environ.get("TZ"):
        return os.environ["TZ"]
    zonefile = Path("/etc/timezone")
    if zonefile.is_file():
        return zonefile.read_text().strip()
    resolved = str(Path("/etc/localtime").resolve())
    if "/zoneinfo/" in resolved:
        return resolved.split("/zoneinfo/", 1)[1]
    return "UTC"  # Hosts without an IANA database identity use the explicit UTC baseline.


class AgentConfig(StrictModel):
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    timezone: str = Field(default_factory=local_timezone)
    # User budget, not a claim about every provider's actual model capacity.
    # None requires a known model profile or explicit configuration to run.
    context_window: PositiveInt | None = 200_000
    output_tokens: PositiveInt = 4096
    summary_ai: ID | None = None
    summary_context_window: PositiveInt | None = None
    trigger_tokens: PositiveInt = 180_000
    keep_tokens: PositiveInt = 40_000
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
        if self.keep_tokens >= self.trigger_tokens:
            raise ValueError("保留 token 数必须低于触发阈值")
        if self.context_window is not None:
            if self.output_tokens >= self.context_window:
                raise ValueError("模型容量扣除输出预留后必须有剩余空间")
        if self.summary_context_window is not None:
            if self.summary_max_tokens >= self.summary_context_window:
                raise ValueError("摘要模型容量扣除输出预留后必须有剩余空间")
        return self
