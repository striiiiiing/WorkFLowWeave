"""分类上游错误，并在保留诊断全文的同时脱敏已知认证凭据。"""

from __future__ import annotations

import re
import traceback

import httpx
from openai import APIConnectionError, APIStatusError

from workflowweave.models import ErrorInfo

_AUTH = re.compile(r"(?i)\b(Bearer|Basic)\s+[^\s\"',;<>]+")


class ModelError(Exception):
    """携带错误码、重试资格和上游诊断的内部模型异常。

    uncertain 表示无法确认请求是否被上游接受，此时服务层不自动重试。
    report 由请求执行层填入脱敏后的结构化错误，供最终结果使用。
    """

    def __init__(
        self, code: str, message: str, *, retryable: bool = False,
        uncertain: bool = False, status_code: int | None = None,
        response_body: str | None = None,
    ):
        """记录异常分类，不主动重试，也不在构造阶段格式化异常链。

        Args:
            code: 对外可识别的错误码。
            message: 错误描述。
            retryable: 此类错误是否允许进入服务层重试策略。
            uncertain: 请求是否存在已被上游接受的可能。
            status_code: 已知的上游 HTTP 状态码。
            response_body: 可选的上游响应全文，尚未脱敏。
        """
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.uncertain = uncertain
        self.status_code = status_code
        self.response_body = response_body
        self.report: ErrorInfo | None = None


def model_error(exc: Exception) -> ModelError:
    """将 SDK、HTTP 和协议异常归一为服务层错误分类。

    408、429、5xx 以及建立连接前的失败允许重试；读写阶段的网络故障标记
    为 uncertain。既有 ModelError 保持原分类，其他异常归为 invalid_response。
    """
    if isinstance(exc, ModelError):
        return exc
    if isinstance(exc, (APIStatusError, httpx.HTTPStatusError)):
        status = exc.response.status_code
        code = {
            401: "authentication_failed", 403: "authentication_failed",
            408: "provider_timeout", 429: "rate_limited",
        }.get(status, "provider_unavailable" if 500 <= status < 600 else "provider_rejected")
        return ModelError(code, "模型服务返回错误状态", status_code=status,
                          retryable=status in (408, 429) or 500 <= status < 600,
                          response_body=exc.response.text)
    if isinstance(exc, (APIConnectionError, httpx.TransportError)):
        cause = exc
        while isinstance(cause, APIConnectionError) and cause.__cause__ is not None:
            cause = cause.__cause__
        unaccepted = isinstance(cause, (httpx.ConnectTimeout, httpx.PoolTimeout, httpx.ConnectError))
        return ModelError("network_error", "模型服务连接失败", retryable=unaccepted,
                          uncertain=not unaccepted)
    return ModelError("invalid_response", "模型调用或响应处理失败")


def error_info(exc: Exception, *, credential: str | None = None) -> ErrorInfo:
    """生成包含异常全文、异常链和可用 HTTP 正文的 ErrorInfo。

    credential 为本次已解析的凭据；其原文及 Bearer/Basic 认证值会被替换，
    正文不截断。本函数不会自动识别响应中所有可能的业务敏感字段。
    """
    error = model_error(exc)

    def redact(text: str) -> str:
        """替换本次已知凭据及认证值，保留其余诊断文本。"""
        if credential:
            text = text.replace(credential, "[REDACTED]")
        return _AUTH.sub(r"\1 [REDACTED]", text)

    details = {
        "exception_type": type(exc).__name__, "exception": redact(str(exc)),
        "traceback": redact("".join(traceback.format_exception(exc))),
        "status_code": error.status_code, "uncertain": error.uncertain,
        "retryable": error.retryable,
    }
    if error.response_body is not None:
        details["response_body"] = redact(error.response_body)
    return ErrorInfo(code=error.code, message=redact(str(error)), details=details)
