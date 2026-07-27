from __future__ import annotations

import json
import os
from pathlib import Path

from .approval_gate import (
    _find_approved_request,
    _is_sensitive_objective,
    handle_approval_event,
)
from .autonomous_planning import announce_plan, resolve_continuation
from .bot import AmosclaudBot, WRITE_ASSOCIATIONS, parse_command
from .comment_style import compact_public_comment
from .intelligence_router import handle_intelligence_request
from .privacy_gate import requires_private_work, route_private_work
from .professional import run_professional_from_environment
from .security_context import record_human_approval
from .status_board import handle_status_request

PRIVATE_ROUTE_MARKER = Path("/tmp/amosclaud-private-routed")
_ORIGINAL_POST_COMMENT = AmosclaudBot.post_comment


def _compact_post_comment(self: AmosclaudBot, issue_number: int, body: str) -> None:
    _ORIGINAL_POST_COMMENT(self, issue_number, compact_public_comment(body))


def _install_compact_comment_mode() -> None:
    """Apply one compact public-comment policy across bot, approval, privacy, and review layers."""
    AmosclaudBot.post_comment = _compact_post_comment


def _handle_private_issue_comment(bot: AmosclaudBot, payload: dict) -> int | None:
    comment = payload.get("comment") or {}
    raw = str(comment.get("body") or "")
    normalized = " ".join(raw.strip().split()).lower()

    if normalized.startswith("@amosclaud approve") or normalized.startswith("@amosclaud-bot approve"):
        return None
    if normalized.startswith("@amosclaud deny") or normalized.startswith("@amosclaud-bot deny"):
        return None

    command, objective = parse_command(raw)
    if not command or not objective or not requires_private_work(objective):
        return None

    issue = payload.get("issue") or {}
    source_number = issue.get("number", "unknown")
    association = str(comment.get("author_association") or "NONE").upper()

    if association not in WRITE_ASSOCIATIONS:
        bot.post_comment(
            int(source_number),
            "### Amosclaud Bot — Private work request blocked\n"
            "This request requires protected private processing. Only OWNER, MEMBER, or COLLABORATOR may route work into the owner-only private queue.",
        )
        PRIVATE_ROUTE_MARKER.write_text("blocked\n", encoding="utf-8")
        return 0

    route = route_private_work(
        source_bot=bot,
        title=f"[Amosclaud Private Work] {command} request from public issue #{source_number}",
        body=(
            "## Amosclaud Private Work Queue\n\n"
            f"**Source repository:** `{bot.repository}`\n"
            f"**Source issue:** `#{source_number}`\n"
            f"**Command:** `{command}`\n\n"
            "### Objective\n"
            f"{objective}\n\n"
            "This work was routed away from the public issue because Amosclaud classified it as serious/private work."
        ),
    )

    PRIVATE_ROUTE_MARKER.write_text("private\n", encoding="utf-8")

    if route.configured:
        bot.post_comment(
            int(source_number),
            "### Amosclaud Bot — Private work protected\n"
            "This request was classified as serious/private work and routed to the owner-only private work queue. "
            "Details and processing records will not be repeated in this public issue.",
        )
    else:
        bot.post_comment(
            int(source_number),
            "### Amosclaud Bot — Private work required\n"
            "This request was classified as serious/private work, so public processing has been stopped to avoid disclosure. "
            "Configure the owner-only private work queue (`AMOSCLAUD_PRIVATE_REPOSITORY` + `AMOSCLAUD_PRIVATE_TOKEN`) "
            "or use a GitHub Repository Security Advisory for security-vulnerability work.",
        )
    return 0


def _pending_sensitive_approval(bot: AmosclaudBot, payload: dict, event_name: str) -> tuple[int, str, int, str] | None:
    if event_name != "issue_comment":
        return None
    comment = payload.get("comment") or {}
    command, objective = parse_command(str(comment.get("body") or ""))
    if command != "fix" or not objective or not _is_sensitive_objective(objective):
        return None
    issue = payload.get("issue") or {}
    source_number = issue.get("number")
    if not isinstance(source_number, int):
        return None
    approved = _find_approved_request(
        bot,
        source_number=source_number,
        objective=objective,
    )
    if approved is None:
        return None
    association = str(comment.get("author_association") or "NONE").upper()
    return source_number, objective, approved, association


def run_dispatcher_from_environment() -> int:
    """Route GitHub events through privacy, intelligence, approval, planning, and execution."""
    _install_compact_comment_mode()

    event_name = os.getenv("GITHUB_EVENT_NAME", "")
    event_path = os.getenv("GITHUB_EVENT_PATH", "")
    repository = os.getenv("GITHUB_REPOSITORY", "")
    token = os.getenv("GITHUB_TOKEN", "")
    privacy_only = os.getenv("AMOSCLAUD_PRIVACY_ONLY", "") == "1"

    if not event_path or not repository:
        raise RuntimeError("GITHUB_EVENT_PATH and GITHUB_REPOSITORY are required")

    payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    bot = AmosclaudBot(repository=repository, token=token, workspace=Path.cwd())

    if event_name == "issue_comment":
        if resolve_continuation(bot, payload):
            return 0
        privacy_result = _handle_private_issue_comment(bot, payload)
        if privacy_result is not None:
            return privacy_result
        if privacy_only:
            return 0

        intelligence_result = handle_intelligence_request(bot, payload)
        if intelligence_result is not None:
            return intelligence_result

        status_result = handle_status_request(bot, payload)
        if status_result is not None:
            return status_result

    if PRIVATE_ROUTE_MARKER.exists():
        return 0

    pending_approval = _pending_sensitive_approval(bot, payload, event_name)
    approval_result = handle_approval_event(bot, payload, event_name)
    if approval_result is not None:
        return approval_result
    if pending_approval is not None:
        source_number, objective, approval_number, association = pending_approval
        record_human_approval(
            source_number=source_number,
            approval_number=approval_number,
            objective=objective,
            actor_association=association,
        )

    if event_name == "issue_comment":
        announce_plan(bot, payload)

    return run_professional_from_environment()


if __name__ == "__main__":
    raise SystemExit(run_dispatcher_from_environment())
