"""Bridge authenticated native repository requests to the coding runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from amosclaud_os.agent.coding_runtime import AutonomousCodingRuntime
from src.agent.model import AutonomousModelGateway


def run_native_coding_if_requested(
    *,
    objective: str,
    mode: str,
    authorized_writes: bool,
    workspace: str,
    metadata: dict[str, Any],
) -> dict[str, Any] | None:
    """Run a native coding transaction only for server-authorized writes."""

    if mode != "fix" or not authorized_writes:
        return None
    if not metadata.get("repository_id"):
        return None
    if metadata.get("authorization_source") != "signed-in-session":
        return None

    result = AutonomousCodingRuntime(
        Path(workspace),
        model=AutonomousModelGateway(),
    ).run(
        objective=objective,
        source_branch=str(metadata.get("branch") or "main"),
        author_name=str(metadata.get("author_name") or "Amosclaud Agent"),
        author_email=str(
            metadata.get("author_email") or "agent@amosclaud.local"
        ),
    )
    return result.to_dict()
