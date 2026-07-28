from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONTINUE_PHRASES = frozenset(
    {
        "continue",
        "resume",
        "proceed",
        "go ahead",
        "continue the task",
        "resume the task",
        "proceed with the task",
        "proceed with the repair",
        "proceed with the fix",
        "go ahead with the task",
        "finish the remaining work",
        "finish remaining work",
        "complete the remaining work",
    }
)
STATE_PATH = Path("/tmp/amosclaud-continuation.json")


def normalize_request(text: str) -> str:
    normalized = " ".join((text or "").strip().split()).lower()
    for name in ("@amosclaud-bot", "@amosclaud"):
        if normalized.startswith(name):
            return normalized[len(name) :].strip().rstrip(".")
    return normalized.rstrip(".")


def is_continue_request(text: str) -> bool:
    return normalize_request(text) in CONTINUE_PHRASES


def write_continuation_state(plan: dict[str, str] | None) -> None:
    payload: dict[str, Any] = {"version": 1, "found": bool(plan)}
    if plan:
        payload.update(
            {
                "command": str(plan.get("command") or "").strip(),
                "objective": " ".join(str(plan.get("objective") or "").split()),
            }
        )
    STATE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def read_continuation_state() -> dict[str, Any] | None:
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return None
    if payload.get("found") is not True:
        return {"found": False}
    command = str(payload.get("command") or "").strip()
    objective = " ".join(str(payload.get("objective") or "").split())
    if command not in {"fix", "inspect", "review", "verify"} or not objective:
        return None
    return {"found": True, "command": command, "objective": objective}
