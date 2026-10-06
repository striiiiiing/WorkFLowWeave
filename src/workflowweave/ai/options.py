"""集中校验渠道地址、显式模型选择及每个模型的 JSON 参数。"""

from urllib.parse import urlparse

from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import AIConfig

REASONING_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
OPENAI_COMPATIBLE_PROVIDER = "openai_compatible_api"
LEGACY_HTTP_PROVIDER = "http"
_MANAGED_OPTIONS = frozenset({
    "temperature", "top_k", "model", "messages", "api_key", "base_url", "timeout",
    "retries", "max_retries", "stream", "stream_options", "headers", "extra_headers",
    "authorization", "auth", "http_client", "extra_body", "extra_query",
})


def validate_config(config: AIConfig, providers, model: str | None = None) -> None:
    """在不执行网络请求的情况下检查已解析的 AI 配置。

    Args:
        config: 已通过 AIConfig 数据结构校验的配置。
        providers: 当前可用的渠道类型集合或工厂映射。
        model: 可选的本次模型名；提供时必须存在于 config.models。

    Raises:
        WorkFLowWeaveError: 渠道未注册、HTTP 地址不合法、覆盖管理字段，或思考参数
            类型、强度及组合不合法。始终检查全部模型，而非只检查所选模型。
    """
    if config.provider not in providers:
        raise WorkFLowWeaveError(
            "provider_missing", "API 格式不可用，请选择 OpenAI Compatible API",
            {"field": "provider", "available": ["OpenAI Compatible API"]},
        )
    if config.provider in {OPENAI_COMPATIBLE_PROVIDER, LEGACY_HTTP_PROVIDER}:
        parsed = urlparse(config.base_url or "")
        try:
            port = parsed.port
        except ValueError:
            port = -1
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or port == -1):
            raise WorkFLowWeaveError("invalid_config", "OpenAI Compatible API 服务地址无效", {"field": "base_url"})
    if model is not None and model not in config.models:
        raise WorkFLowWeaveError("invalid_config", "选择的 AI model 不存在", {"field": "model"})
    for options in config.models.values():
        bad = sorted(_MANAGED_OPTIONS & options.keys())
        if bad:
            raise WorkFLowWeaveError("invalid_config", "模型参数覆盖管理字段", {"fields": bad})
        if "enable_thinking" in options and type(options["enable_thinking"]) is not bool:
            raise WorkFLowWeaveError("invalid_config", "enable_thinking 必须是布尔值")
        effort = options.get("reasoning_effort")
        if "reasoning_effort" in options and (
            not isinstance(effort, str) or effort not in REASONING_EFFORTS
        ):
            raise WorkFLowWeaveError("invalid_config", "reasoning_effort 必须是 low/medium/high/xhigh/max")
        if options.get("enable_thinking") is False and "reasoning_effort" in options:
            raise WorkFLowWeaveError("invalid_config", "关闭思考不能同时指定思考强度")
