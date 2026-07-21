from __future__ import annotations

import json
import os
from pathlib import Path

from .approval_gate import handle_approval_event
from .bot import AmosclaudBot
from .professional import run_professional_from_environment


def run_dispatcher_from_environment() -> int:
    """Route every supported GitHub event through approval, professional, then base bot handling.

    The workflow intentionally invokes this dispatcher for every issue comment. Command
    filtering lives in Python so harmless formatting/case changes in a GitHub comment do
    not prevent the job from starting at all.
    """
    event_name = os.getenv("GITHUB_EVENT_NAME", "")
    event_path = os.getenv("GITHUB_EVENT_PATH", "")
    repository = os.getenv("GITHUB_REPOSITORY", "")
    token = os.getenv("GITHUB_TOKEN", "")

    if not event_path or not repository:
        raise RuntimeError("GITHUB_EVENT_PATH and GITHUB_REPOSITORY are required")

    payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    bot = AmosclaudBot(repository=repository, token=token, workspace=Path.cwd())

    approval_result = handle_approval_event(bot, payload, event_name)
    if approval_result is not None:
        return approval_result

    return run_professional_from_environment()


if __name__ == "__main__":
    raise SystemExit(run_dispatcher_from_environment())
