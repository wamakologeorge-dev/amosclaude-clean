from __future__ import annotations

import hashlib
from typing import Any

from .bot import AmosclaudBot, WRITE_ASSOCIATIONS, parse_command

SENSITIVE_HINTS = (
    "production",
    "deploy",
    "deployment",
    "workflow",
    "permission",
    "authentication",
    "authorization",
    "secret",
    "credential",
    "token",
    "infrastructure",
    "security",
)

HIGH_RISK_PREFIXES = (
    ".github/workflows/",
    ".github/actions/",
    "Infrastructure/",
    "infrastructure/",
)

HIGH_RISK_FILES = {
    "SECURITY.md",
    ".github/SECURITY.md",
    "CODEOWNERS",
    ".github/CODEOWNERS",
    "Dockerfile",
    "railway.json",
    "vercel.json",
}

APPROVAL_MARKER = "<!-- amosclaud-approval-source:"
APPROVAL_CONSUMED_MARKER = "<!-- amosclaud-approval-consumed -->"


def _is_sensitive_objective(objective: str) -> bool:
    lowered = (objective or "").lower()
    return any(hint in lowered for hint in SENSITIVE_HINTS)


def _normalize_objective(objective: str) -> str:
    return " ".join((objective or "").strip().lower().split())


def _approval_source(source_number: int | str, objective: str) -> str:
    """Bind an approval to one issue and one exact normalized objective."""
    digest = hashlib.sha256(_normalize_objective(objective).encode("utf-8")).hexdigest()[:16]
    return f"issue-comment-{source_number}-{digest}"


def _high_risk_files(files: list[dict[str, Any]]) -> list[str]:
    names = [str(item.get("filename") or "") for item in files]
    return [
        name
        for name in names
        if name in HIGH_RISK_FILES
        or any(name.startswith(prefix) for prefix in HIGH_RISK_PREFIXES)
        or any(hint in name.lower() for hint in ("security", "auth", "permission", "secret", "credential"))
    ]


def _issues(bot: AmosclaudBot, *, state: str) -> list[dict[str, Any]]:
    issues = bot._request("GET", f"/repos/{bot.repository}/issues?state={state}&per_page=100")
    return issues if isinstance(issues, list) else []


def _matching_approval_issue(
    bot: AmosclaudBot,
    source: str,
    *,
    state: str = "all",
    legacy_objective: str | None = None,
) -> dict[str, Any] | None:
    marker = f"{APPROVAL_MARKER}{source} -->"
    for issue in _issues(bot, state=state):
        if issue.get("pull_request"):
            continue
        body = str(issue.get("body") or "")
        if marker not in body:
            continue
        if legacy_objective is not None and f"`{legacy_objective}`" not in body:
            continue
        return issue
    return None


def _existing_open_approval(bot: AmosclaudBot, source: str) -> int | None:
    issue = _matching_approval_issue(bot, source, state="open")
    if issue is None:
        return None
    number = issue.get("number")
    return int(number) if isinstance(number, int) else None


def _approval_decision(bot: AmosclaudBot, issue_number: int) -> str | None:
    comments = bot._request(
        "GET",
        f"/repos/{bot.repository}/issues/{issue_number}/comments?per_page=100",
    )
    if not isinstance(comments, list):
        return None

    decision: str | None = None
    consumed = False
    for comment in comments:
        body = str(comment.get("body") or "")
        if "**Decision:** **APPROVED**" in body:
            decision = "APPROVED"
        elif "**Decision:** **DENIED**" in body:
            decision = "DENIED"
        if APPROVAL_CONSUMED_MARKER in body:
            consumed = True

    if consumed:
        return "CONSUMED"
    return decision


def _find_approved_request(
    bot: AmosclaudBot,
    *,
    source_number: int | str,
    objective: str,
) -> int | None:
    """Return one unconsumed approval bound to this exact sensitive request.

    New approvals are keyed by an objective digest. A narrow compatibility path
    accepts older approvals (created before objective binding existed) only when
    the approval issue body contains the exact original objective.
    """
    source = _approval_source(source_number, objective)
    issue = _matching_approval_issue(bot, source, state="all")

    if issue is None:
        legacy_source = f"issue-comment-{source_number}"
        issue = _matching_approval_issue(
            bot,
            legacy_source,
            state="all",
            legacy_objective=objective,
        )

    if issue is None:
        return None
    number = issue.get("number")
    if not isinstance(number, int):
        return None
    return number if _approval_decision(bot, number) == "APPROVED" else None


def _consume_approval(bot: AmosclaudBot, approval_number: int, source_number: int | str) -> None:
    bot.post_comment(
        approval_number,
        "### Amosclaud Approval — Execution authorized\n"
        f"{APPROVAL_CONSUMED_MARKER}\n"
        f"Approval consumed by the re-run from source #{source_number}. "
        "This approval cannot authorize another execution.",
    )


def _create_approval_issue(
    bot: AmosclaudBot,
    *,
    source: str,
    title: str,
    reason_lines: list[str],
    requested_capability: str,
) -> int:
    existing = _existing_open_approval(bot, source)
    if existing is not None:
        return existing

    reasons = "\n".join(f"- {line}" for line in reason_lines) or "- Sensitive Amosclaud action detected"
    body = (
        f"{APPROVAL_MARKER}{source} -->\n"
        "## Amosclaud Human Approval Required\n\n"
        "**Status:** `WAITING_FOR_HUMAN_APPROVAL`\n\n"
        f"**Requested capability:** {requested_capability}\n\n"
        "### Reason\n"
        f"{reasons}\n\n"
        "### Decision\n"
        "A trusted repository human must comment one of:\n\n"
        "- `@amosclaud approve`\n"
        "- `@amosclaud deny`\n\n"
        "Approval is deliberately separate from execution. After approval, re-run the original command so the execution remains explicit and auditable. Each approval authorizes one execution only."
    )
    created = bot._request(
        "POST",
        f"/repos/{bot.repository}/issues",
        {"title": f"[Amosclaud Approval Required] {title}", "body": body},
    )
    number = created.get("number") if isinstance(created, dict) else None
    if not isinstance(number, int):
        raise RuntimeError("GitHub did not return an approval issue number")
    return number


def _record_decision(bot: AmosclaudBot, payload: dict[str, Any], command: str) -> int | None:
    issue = payload.get("issue") or {}
    body = str(issue.get("body") or "")
    title = str(issue.get("title") or "")
    if APPROVAL_MARKER not in body and not title.startswith("[Amosclaud Approval Required]"):
        return None

    association = str((payload.get("comment") or {}).get("author_association") or "NONE").upper()
    number = issue.get("number")
    if not isinstance(number, int):
        return 0

    if association not in WRITE_ASSOCIATIONS:
        bot.post_comment(number, "### Amosclaud Approval\nDecision rejected: only OWNER, MEMBER, or COLLABORATOR may approve or deny sensitive actions.")
        return 0

    state = "APPROVED" if command == "approve" else "DENIED"
    bot.post_comment(
        number,
        f"### Amosclaud Approval\n**Decision:** **{state}**\n\nThe approval record is now auditable. Re-run the original sensitive command only if the decision is APPROVED.",
    )
    bot._request("PATCH", f"/repos/{bot.repository}/issues/{number}", {"state": "closed"})
    return 0


def handle_approval_event(bot: AmosclaudBot, payload: dict[str, Any], event_name: str) -> int | None:
    if event_name == "issue_comment":
        comment = payload.get("comment") or {}
        command, objective = parse_command(str(comment.get("body") or ""))
        normalized = " ".join(str(comment.get("body") or "").strip().split()).lower()

        if normalized.startswith("@amosclaud approve") or normalized.startswith("@amosclaud-bot approve"):
            return _record_decision(bot, payload, "approve")
        if normalized.startswith("@amosclaud deny") or normalized.startswith("@amosclaud-bot deny"):
            return _record_decision(bot, payload, "deny")

        if command == "fix" and _is_sensitive_objective(objective):
            issue = payload.get("issue") or {}
            source_number = issue.get("number", "unknown")

            approved = _find_approved_request(
                bot,
                source_number=source_number,
                objective=objective,
            )
            if approved is not None:
                _consume_approval(bot, approved, source_number)
                bot.post_comment(
                    int(source_number),
                    f"### Amosclaud Bot — Approval verified\nApproval issue #{approved} authorizes this one execution. Proceeding with Amosclaud-Fixer.",
                )
                return None

            approval = _create_approval_issue(
                bot,
                source=_approval_source(source_number, objective),
                title=f"Sensitive Amosclaud-Fixer request from #{source_number}",
                reason_lines=[f"Sensitive capability keyword detected in requested repair: `{objective}`"],
                requested_capability="Amosclaud-Fixer",
            )
            bot.post_comment(
                int(source_number),
                f"### Amosclaud Bot — Human approval required\nSensitive repair execution is paused. Approval issue: #{approval}",
            )
            return 0

    if event_name == "pull_request":
        pr = payload.get("pull_request") or {}
        number = pr.get("number") or (payload.get("number"))
        if not isinstance(number, int):
            return None
        files = bot._request("GET", f"/repos/{bot.repository}/pulls/{number}/files?per_page=100")
        files = files if isinstance(files, list) else []
        risky = _high_risk_files(files)
        if risky:
            approval = _create_approval_issue(
                bot,
                source=f"pull-request-{number}",
                title=f"Sensitive changes in PR #{number}",
                reason_lines=[f"High-risk path changed: `{name}`" for name in risky[:12]],
                requested_capability="Pull request merge/review decision",
            )
            bot.post_comment(number, f"### Amosclaud Bot — Human approval required\nSensitive paths were detected. Approval issue: #{approval}")
            return 0

    return None
