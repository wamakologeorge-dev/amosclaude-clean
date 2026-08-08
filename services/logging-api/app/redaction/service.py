from __future__ import annotations

import re
from typing import Any

SENSITIVE_KEYS = {
    "password", "passwd", "authorization", "cookie", "api_key", "apikey",
    "access_token", "refresh_token", "private_key", "secret", "database_url",
    "redis_url", "client_secret", "session_token",
}
TOKEN_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[a-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)[^\s,;]+"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
)


def _is_sensitive(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in SENSITIVE_KEYS or normalized.endswith(("_token", "_secret", "_password"))


def redact_text(value: str) -> str:
    redacted = value
    for pattern in TOKEN_PATTERNS:
        if pattern.groups:
            redacted = pattern.sub(r"\1[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def redact(value: Any, *, key: str = "") -> Any:
    if key and _is_sensitive(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): redact(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
