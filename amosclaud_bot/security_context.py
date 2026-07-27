"""Runner-local approval context shared by the approval gate and Bot.

The file is stored outside the repository and is useful only during the current
GitHub Actions job. The signed command grant remains the durable authorization.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from src.amosclaud_security import objective_digest

APPROVAL_CONTEXT_PATH = Path("/tmp/amosclaud-security-approval.json")
MAX_CONTEXT_AGE_SECONDS = 600


def record_human_approval(
    *,
    source_number: int | str,
    approval_number: int,
    objective: str,
    actor_association: str,
) -> None:
    payload = {
        "source_number": str(source_number),
        "approval_number": int(approval_number),
        "objective_digest": objective_digest(objective),
        "actor_association": actor_association.upper(),
        "recorded_at": int(time.time()),
    }
    APPROVAL_CONTEXT_PATH.write_text(
        json.dumps(payload, sort_keys=True),
        encoding="utf-8",
    )
    APPROVAL_CONTEXT_PATH.chmod(0o600)


def consume_human_approval(
    *,
    source_number: int | str,
    objective: str,
) -> dict[str, Any] | None:
    try:
        payload = json.loads(APPROVAL_CONTEXT_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    finally:
        APPROVAL_CONTEXT_PATH.unlink(missing_ok=True)
    if not isinstance(payload, dict):
        return None
    if payload.get("source_number") != str(source_number):
        return None
    if payload.get("objective_digest") != objective_digest(objective):
        return None
    recorded_at = int(payload.get("recorded_at") or 0)
    if recorded_at <= 0 or int(time.time()) - recorded_at > MAX_CONTEXT_AGE_SECONDS:
        return None
    approval_number = payload.get("approval_number")
    if not isinstance(approval_number, int):
        return None
    return payload
