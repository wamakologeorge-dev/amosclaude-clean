from __future__ import annotations

import hashlib
import re
from typing import Any

UUIDS = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}\b")
NUMBERS = re.compile(r"\b\d+\b")
WHITESPACE = re.compile(r"\s+")


def normalize_message(message: str) -> str:
    value = UUIDS.sub("<uuid>", message.lower())
    value = NUMBERS.sub("<n>", value)
    return WHITESPACE.sub(" ", value).strip()


def fingerprint(event: dict[str, Any]) -> str:
    source = "|".join([
        str(event.get("tenant_id", "")), str(event.get("service", "")),
        str(event.get("level", "")), normalize_message(str(event.get("message", ""))),
    ])
    return hashlib.sha256(source.encode("utf-8", errors="replace")).hexdigest()
