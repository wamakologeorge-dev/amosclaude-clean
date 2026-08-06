from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .approval_gate import (
    _approval_source,
    _consume_approval,
    _create_approval_issue,
    _find_approved_request,
    _record_decision,
)
from .bot import AmosclaudBot, WRITE_ASSOCIATIONS, parse_command

PRIVATE_OBJECTIVE_HINTS = (
    "leaked secret",
    "exposed secret",
    "leaked key",
    "exposed key",
    "credential leak",
    "password leak",
    "private information",
    "personal information",
    "private data",
    "recovery code leak",
)

PRIVATE_DATA_FILES = {
    ".env",
    "secrets.json",
    "credentials.json",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}
PRIVATE_DATA_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
PRIVATE_DATA_PATCH_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY",
        r"social[ _-]?security[ _-]?number",
        r"recovery[ _-]?(?:phrase|seed|code)",
        r"(?:api[ _-]?key|client[ _-]?secret|password|access[ _-]?token)"
        r"\s*[:=]\s*['\"]?(?!\$\{\{|<|example|test|placeholder|redacted)"
        r"[A-Za-z0-9_./+=-]{16,}",
    )
)


def _is_sensitive_objective(objective: str) -> bool:
    """Return true only for explicit private-data or credential remediation."""
    lowered = " ".join((objective or "").lower().split())
    return any(hint in lowered for hint in PRIVATE_OBJECTIVE_HINTS)


def _normalize_repo_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _private_data_risks(files: list[dict[str, Any]]) -> list[str]:
    """Detect high-confidence private information without treating code paths as risky."""
    findings: list[str] = []
    for item in files:
        paths = [str(item.get("filename") or "")]
        previous = str(item.get("previous_filename") or "")
        if previous:
            paths.append(previous)

        for raw_path in paths:
            normalized = _normalize_repo_path(raw_path)
            name = Path(normalized).name.lower()
            if name in PRIVATE_DATA_FILES or name.endswith(PRIVATE_DATA_SUFFIXES):
                findings.append(f"Private or credential-bearing file changed: `{normalized}`")

        patch = str(item.get("patch") or "")
        if patch and any(pattern.search(patch) for pattern in PRIVATE_DATA_PATCH_PATTERNS):
            filename = _normalize_repo_path(str(item.get("filename") or "unknown"))
            findings.append(f"Potential private information detected in `{filename}`")

    return list(dict.fromkeys(findings))


def handle_approval_event(
    bot: AmosclaudBot,
    payload: dict[str, Any],
    event_name: str,
) -> int | None:
    """Pause only private-data remediation; allow ordinary verified repairs to proceed."""
    if event_name == "issue_comment":
        comment = payload.get("comment") or {}
        raw = str(comment.get("body") or "")
        normalized = " ".join(raw.strip().split()).lower()
        command, objective = parse_command(raw)

        if normalized.startswith("@amosclaud approve") or normalized.startswith(
            "@amosclaud-bot approve"
        ):
            return _record_decision(bot, payload, "approve")
        if normalized.startswith("@amosclaud deny") or normalized.startswith(
            "@amosclaud-bot deny"
        ):
            return _record_decision(bot, payload, "deny")

        if command != "fix" or not _is_sensitive_objective(objective):
            return None

        issue = payload.get("issue") or {}
        source_number = issue.get("number", "unknown")
        association = str(comment.get("author_association") or "NONE").upper()
        if association not in WRITE_ASSOCIATIONS:
            bot.post_comment(
                int(source_number),
                "### Amosclaud Bot — Private-data repair blocked\n"
                "Only OWNER, MEMBER, or COLLABORATOR may authorize handling private information.",
            )
            return 0

        approved = _find_approved_request(
            bot,
            source_number=source_number,
            objective=objective,
        )
        if approved is not None:
            _consume_approval(bot, approved, source_number)
            bot.post_comment(
                int(source_number),
                f"### Amosclaud Bot — Approval verified\n"
                f"Approval issue #{approved} authorizes this private-data repair once.",
            )
            return None

        approval = _create_approval_issue(
            bot,
            source=_approval_source(source_number, objective),
            title=f"Private-data repair request from #{source_number}",
            reason_lines=[
                "The requested repair explicitly handles leaked credentials or private information."
            ],
            requested_capability="Private-data remediation",
        )
        bot.post_comment(
            int(source_number),
            "### Amosclaud Bot — Human approval required\n"
            f"Private-data remediation is paused. Approval issue: #{approval}",
        )
        return 0

    if event_name == "pull_request":
        pull_request = payload.get("pull_request") or {}
        number = pull_request.get("number") or payload.get("number")
        if not isinstance(number, int):
            return None
        files = bot._request("GET", f"/repos/{bot.repository}/pulls/{number}/files?per_page=100")
        files = files if isinstance(files, list) else []
        risks = _private_data_risks(files)
        if not risks:
            return None

        approval = _create_approval_issue(
            bot,
            source=f"pull-request-{number}",
            title=f"Private information detected in PR #{number}",
            reason_lines=risks[:12],
            requested_capability="Private-data removal or continuation",
        )
        bot.post_comment(
            number,
            "### Amosclaud Bot — Human approval required\n"
            "Potential private information or credential material was detected. "
            f"Approval issue: #{approval}",
        )
        return 0

    return None
