"""Contracts for the Luna -> Sol business evaluation."""

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal


@dataclass(frozen=True)
class Route:
    name: Literal["original", "generic", "custom"]
    compressor_model: str | None
    analyzer_model: str
    compression_prompt: str | None
    analysis_prompt: str
    compression_effort: str | None = None
    analysis_effort: str = "medium"

    @property
    def compression_prompt_hash(self) -> str | None:
        if self.compression_prompt is None:
            return None
        return sha256(self.compression_prompt.encode()).hexdigest()


ANALYSIS_PROMPT = "输出基于输入证据的最终业务报告，区分事实与推断。"
GENERIC_COMPRESSION_PROMPT = "压缩输入，保留后续任务所需的事实、数字、实体和关系，不添加输入中不存在的信息。"
CUSTOM_COMPRESSION_PROMPT = "围绕当前任务压缩输入：优先保留可直接支持答案的证据、实体关系、时间顺序和冲突；标注不确定性，不添加输入中不存在的信息。"


ROUTES = (
    Route("original", None, "gpt-6.1-sol", None, ANALYSIS_PROMPT),
    Route("generic", "gpt-6-luna", "gpt-6.1-sol", GENERIC_COMPRESSION_PROMPT, ANALYSIS_PROMPT, "low"),
    Route("custom", "gpt-6-luna", "gpt-6.1-sol", CUSTOM_COMPRESSION_PROMPT, ANALYSIS_PROMPT, "low"),
)


def validate_routes(routes: tuple[Route, ...] = ROUTES) -> None:
    names = {route.name for route in routes}
    if names != {"original", "generic", "custom"}:
        raise ValueError("routes must contain original, generic and custom")
    original = next(route for route in routes if route.name == "original")
    for route in routes:
        if route.analyzer_model != original.analyzer_model or route.analysis_prompt != original.analysis_prompt:
            raise ValueError("analysis configuration must be identical across routes")
    generic = next(route for route in routes if route.name == "generic")
    custom = next(route for route in routes if route.name == "custom")
    if generic.compressor_model != "gpt-6-luna" or custom.compressor_model != "gpt-6-luna":
        raise ValueError("compression model must be gpt-6-luna")
    if generic.compression_prompt == custom.compression_prompt:
        raise ValueError("generic and custom prompts must differ")


def calculate_total_cost(records: list[dict]) -> dict:
    missing = [record["call_id"] for record in records if record.get("status") != "resolved"]
    total = sum(float(usage.get("total_cost", 0)) for record in records for usage in record.get("usage", []))
    return {"total_usd": total if not missing else None, "observed_usd": total, "missing": missing,
            "complete": not missing}
