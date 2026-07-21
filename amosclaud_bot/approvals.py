from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .bot import AmosclaudBot
from .professional import (
    HIGH_RISK_FILES,
    HIGH_RISK_PREFIXES,
    SECURITY_HINTS,
    _changed_file_summary,
    run_professional_from_environment,
)

APPROVAL_TITLE_PREFIX = "[Amosclaud Approval Required]"
TRUSTED_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
RISKY_TOOL_HINTS = (
    "deploy",
    "deployment",
    "workflow",
    "github actions",
    "permission",
    "permissions",
    "authentication",
    "authorization",
    "security",
    "secret",
    "credential",
    "infrastructure",
    "production",
)


def _risk_reasons(files: list[dict[str, Any]]) -> list[str]:
    summary = _changed_file_summary(files)
    reasons: list[str] = []
    if summary["high_risk"]:
        reasons.append(
            "High-risk repository/deployment paths changed: "
            + ", ".join(f"`{name}`" for name in summary["high_risk"][:12])
        )
    if summary["security_related"]:
        reasons.append(
            "Security/authentication-sensitive paths changed: "
            + ", ".join(f"`{name}`" for name in summary["security_related"][:12])
        )
    return reasons


def _tool_requires_approval(command_text: str) -> tuple[bool, list[str]]:
    normalized = " ".join((command_text or "").lower().split())
    if not normalized.startswith(("@amosclaud fix", "@amosclaud-bot fix")):
        return False, []
    matches = sorted({hint for hint in RISKY_TOOL_HINTS if hint in normalized})
    return bool(matches), matches


def _ensure_label(bot: AmosclaudBot, name: str, color: str, description: str) -> None:
    try:
        bot._request(
            "POST",
            f"/repos/{bot.repository}/labels",
            {"name": name, "color": color, "description": description},
        )
    except RuntimeError:
        # Existing labels return a conflict. Approval creation should continue.
        pass


def _find_open_approval(bot: AmosclaudBot, marker: str) -> dict[str, Any] | None:
    query = quote(f'repo:{bot.repository} is:issue is:open in:title "{marker}"')
    result = bot._request("GET", f"/search/issues?q={query}&per_page=10")
    items = result.get("items") if isinstance(result, dict) else []
    if not isinstance(items, list):
        return None
    return next((item for item in items if marker in str(item.get("title") or "")), None)


def _create_approval_issue(
    bot: AmosclaudBot,
    *,
    marker: str,
    subject: str,
    reason_lines: list[str],
    source_url: str = "",
    requested_tool: str = "Amosclaud Autonomous",
) -> dict[str, Any]:
    existing = _find_open_approval(bot, marker)
    if existing:
        return existing

    _ensure_label(bot, "amosclaud:approval-required", "B60205", "Human approval required before Amosclaud continues")
    _ensure_label(bot, "amosclaud:human-review", "D93F0B", "Human review required for a sensitive Amosclaud action")

    reason_text = "\n".join(f"- {line}" for line in reason_lines) or "- Sensitive operation requires human review by policy."
    source_text = f"\n**Source:** {source_url}\n" if source_url else ""
    body = (
        "## Amosclaud human approval request\n\n"
        f"**Subject:** {subject}\n"
        f"**Requested tool/capability:** `{requested_tool}`\n"
        "**Status:** `WAITING_FOR_HUMAN_APPROVAL`\n"
        f"{source_text}\n"
        "### Why approval is required\n"
        f"{reason_text}\n\n"
        "### Human decision\n"
        "A trusted repository owner/member/collaborator should review the request.\n\n"
        "- Approve: comment `@amosclaud approve`\n"
        "- Deny: comment `@amosclaud deny`\n\n"
        "Approval is intentionally separate from execution. After approval, re-run the original Amosclaud command so the action is explicit and auditable.\n\n"
        f"<!-- amosclaud-approval-marker:{marker} -->"
    )
    return bot._request(
        "POST",
        f"/repos/{bot.repository}/issues",
        {
            "title": f"{APPROVAL_TITLE_PREFIX} {marker} — {subject}",
            "body": body,
            "labels": ["amosclaud:approval-required", "amosclaud:human-review"],
        },
    )


def _record_human_decision(bot: AmosclaudBot, payload: dict[str, Any]) -> int | None:
    issue = payload.get("issue") or {}
    title = str(issue.get("title") or "")
    if not title.startswith(APPROVAL_TITLE_PREFIX):
        return None

    comment = payload.get("comment") or {}
    association = str(comment.get("author_association") or "NONE").upper()
    body = " ".join(str(comment.get("body") or "").lower().split())
    if body not in {"@amosclaud approve", "@amosclaud-bot approve", "@amosclaud deny", "@amosclaud-bot deny"}:
        return None

    number = int(issue["number"])
    if association not in TRUSTED_ASSOCIATIONS:
        bot.post_comment(number, "### Amosclaud approval gate\nOnly a trusted OWNER, MEMBER, or COLLABORATOR can approve or deny this request.")
        return 0

    approved = body.endswith("approve")
    label = "amosclaud:approved" if approved else "amosclaud:denied"
    color = "1A7F37" if approved else "CF222E"
    _ensure_label(bot, label, color, "Human decision recorded for an Amosclaud approval request")
    bot._request("POST", f"/repos/{bot.repository}/issues/{number}/labels", {"labels": [label]})
    decision = "APPROVED" if approved else "DENIED"
    bot.post_comment(
        number,
        "### Amosclaud human decision recorded\n"
        f"**Decision:** **{decision}**\n\n"
        + ("Re-run the original Amosclaud command to execute it under this approved intent." if approved else "The requested sensitive action must not be executed."),
    )
    if not approved:
        bot._request("PATCH", f"/repos/{bot.repository}/issues/{number}", {"state": "closed", "state_reason": "not_planned"})
    return 0


def _handle_sensitive_tool_request(bot: AmosclaudBot, payload: dict[str, Any]) -> int | None:
    comment = payload.get("comment") or {}
    command_text = str(comment.get("body") or "")
    requires, matches = _tool_requires_approval(command_text)
    if not requires:
        return None

    issue = payload.get("issue") or {}
    number = int(issue.get("number") or 0)
    marker = f"tool-request-{number}"
    approval = _create_approval_issue(
        bot,
        marker=marker,
        subject=f"Sensitive Amosclaud-Fixer request from #{number}",
        reason_lines=[f"Requested operation matched protected capability: `{match}`" for match in matches],
        source_url=str(issue.get("html_url") or ""),
        requested_tool="Amosclaud-Fixer",
    )
    approval_number = approval.get("number")
    bot.post_comment(
        number,
        "### Amosclaud approval required\n"
        "This repair request involves a protected capability and was **not executed**.\n\n"
        f"Human approval request: #{approval_number}\n"
        "A trusted repository collaborator must review and approve it first.",
    )
    return 0


def _handle_pull_request_risk(bot: AmosclaudBot, payload: dict[str, Any]) -> int | None:
    pr = payload.get("pull_request") or {}
    number = pr.get("number")
    if not isinstance(number, int):
        return None
    files = bot._request("GET", f"/repos/{bot.repository}/pulls/{number}/files?per_page=100")
    if not isinstance(files, list):
        return None
    reasons = _risk_reasons(files)
    if not reasons:
        return 0

    marker = f"PR #{number}"
    approval = _create_approval_issue(
        bot,
        marker=marker,
        subject=f"Human review for sensitive pull request #{number}",
        reason_lines=reasons,
        source_url=str(pr.get("html_url") or ""),
        requested_tool="Amosclaud Professional Review / merge approval",
    )
    approval_number = approval.get("number")
    bot.post_comment(
        number,
        "### Amosclaud automatic human-approval gate\n"
        "Sensitive changes were detected. Amosclaud created a separate human approval issue before recommending merge.\n\n"
        f"Approval issue: #{approval_number}",
    )
    return 0


def run_approval_from_environment() -> int:
    event_name = os.getenv("GITHUB_EVENT_NAME", "")
    event_path = os.getenv("GITHUB_EVENT_PATH", "")
    repository = os.getenv("GITHUB_REPOSITORY", "")
    token = os.getenv("GITHUB_TOKEN", "")
    if not event_path or not repository or not token:
        return run_professional_from_environment()

    payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    bot = AmosclaudBot(repository=repository, token=token, workspace=Path.cwd())

    if event_name == "pull_request":
        handled = _handle_pull_request_risk(bot, payload)
        return 0 if handled is not None else 0

    if event_name == "issue_comment":
        handled = _record_human_decision(bot, payload)
        if handled is not None:
            return handled
        handled = _handle_sensitive_tool_request(bot, payload)
        if handled is not None:
            return handled

    return run_professional_from_environment()


if __name__ == "__main__":
    raise SystemExit(run_approval_from_environment())
