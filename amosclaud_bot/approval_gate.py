from __future__ import annotations

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


def _is_sensitive_objective(objective: str) -> bool:
    lowered = (objective or "").lower()
    return any(hint in lowered for hint in SENSITIVE_HINTS)


def _high_risk_files(files: list[dict[str, Any]]) -> list[str]:
    names = [str(item.get("filename") or "") for item in files]
    return [
        name
        for name in names
        if name in HIGH_RISK_FILES
        or any(name.startswith(prefix) for prefix in HIGH_RISK_PREFIXES)
        or any(hint in name.lower() for hint in ("security", "auth", "permission", "secret", "credential"))
    ]


def _existing_open_approval(bot: AmosclaudBot, source: str) -> int | None:
    issues = bot._request("GET", f"/repos/{bot.repository}/issues?state=open&per_page=100")
    if not isinstance(issues, list):
        return None
    marker = f"{APPROVAL_MARKER}{source} -->"
    for issue in issues:
        if issue.get("pull_request"):
            continue
        if marker in str(issue.get("body") or ""):
            number = issue.get("number")
            return int(number) if isinstance(number, int) else None
    return None


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
        "Approval is deliberately separate from execution. After approval, re-run the original command so the execution remains explicit and auditable."
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
            approval = _create_approval_issue(
                bot,
                source=f"issue-comment-{source_number}",
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
