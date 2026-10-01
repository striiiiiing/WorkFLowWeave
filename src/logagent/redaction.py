"""Shared credential-pattern redaction for logs and Agent text facts."""

import re

_AUTHORIZATION = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/\-=]+")
_NAMED_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|password|secret|token|authorization|credential|master[_-]?key)"
    r"\b\s*[:=]\s*([^\s,;]+)"
)
_URL_CREDENTIAL = re.compile(r"(?i)(https?://)([^/\s:@]+):([^@\s/]+)@")
_SECRET_KEY = re.compile(
    r"(?i)^(api[_-]?key|password|secret|token|authorization|credential|master[_-]?key|ciphertext)$"
)


def redact_text(value: str) -> str:
    value = _AUTHORIZATION.sub(lambda match: f"{match.group(1)} [REDACTED]", value)
    value = _NAMED_SECRET.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)
    return _URL_CREDENTIAL.sub(lambda match: f"{match.group(1)}[REDACTED]@", value)


def redact_data(value):
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_data(item) for item in value]
    if isinstance(value, dict):
        return {key: "[REDACTED]" if _SECRET_KEY.fullmatch(key) else redact_data(item)
                for key, item in value.items()}
    return value
