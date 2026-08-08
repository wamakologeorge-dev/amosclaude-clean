from __future__ import annotations

import re
from typing import Any

SENSITIVE = {"password", "authorization", "cookie", "api_key", "access_token", "refresh_token", "private_key", "secret", "database_url", "redis_url"}
TOKEN = re.compile(r"(?i)(bearer\s+)[a-z0-9._~+/=-]{12,}")


def sanitize(value: Any, key: str = "") -> Any:
    normalized = key.lower().replace("-", "_")
    if normalized in SENSITIVE or normalized.endswith(("_token", "_secret", "_password")):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): sanitize(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return TOKEN.sub(r"\1[REDACTED]", value)
    return value
