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

SENSITIVE_OBJECTIVE_HINTS = (
    ".env",
    "environment variable",
    "secret",
    "credential",
    "password",
    "private key",
    "access token",
    "api key",
    "personal information",
    "personally identifiable",
    "pii",
    "social security",
    "ssn",
    "passport",
    "date of birth",
    "home address",
    "bank account",
    "routing number",
    "credit card",
)

SENSITIVE_FILE_NAMES = {
    "secrets.json",
    "credentials.json",
    "personal-information.json",
    "personal_information.json",
    "pii.json",
    "pii.csv",
}

SENSITIVE_PATH_HINTS = (
    "personal-information",
    "personal_information",
    "personally-identifiable",
    "personally_identifiable",
    "/pii/",
    "customer-private",
    "customer_private",
    "identity-document",
    "identity_document",
)

STRONG_PERSONAL_DATA_PATTERNS = (
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
    re.compile(
        r"(?i)\b(?:social security|ssn|passport|date of birth|dob|home address|"
        r"bank account|routing number|credit card)\b\s*[:=]\s*[^<\s][^\n]*"
    ),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)

SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|secret|password|private[_-]?key|"
    r"credential)\b\s*[:=]\s*['\"]?([^'\"\s#]+)"
)

SAFE_PLACEHOLDER_VALUES = (
    "example",
    "sample",
    "placeholder",
    "changeme",
    "redacted",
    "dummy",
    "test",
    "none",
    "null",
    "${{",
    "${",
    "os.getenv",
    "process.env",
)


def _normalize_repo_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _is_sensitive_objective(objective: str) -> bool:
    lowered = " ".join((objective or "").lower().split())
    return any(hint in lowered for hint in SENSITIVE_OBJECTIVE_HINTS)


def _path_requires_human_approval(path: str) -> bool:
    normalized = _normalize_repo_path(path)
    if not normalized:
        return False
    lowered = normalized.lower()
    name = Path(normalized).name.lower()
    return (
        name == ".env"
        or name.startswith(".env.")
        or name in SENSITIVE_FILE_NAMES
        or any(hint in lowered for hint in SENSITIVE_PATH_HINTS)
    )


def _added_patch_lines(patch: str) -> str:
    lines = []
    for line in (patch or "").splitlines():
        if line.startswith("+++"):
            continue
        if line.startswith("+"):
            lines.append(line[1:])
    return "\n".join(lines)


def _patch_contains_sensitive_information(patch: str) -> bool:
    added = _added_patch_lines(patch)
    if not added:
        return False
    if any(pattern.search(added) for pattern in STRONG_PERSONAL_DATA_PATTERNS):
        return True
    for match in SECRET_ASSIGNMENT.finditer(added):
        value = match.group(1).strip().lower()
        if value and not any(marker in value for marker in SAFE_PLACEHOLDER_VALUES):
            return True
    return False


def _high_risk_files(files: list[dict[str, Any]]) -> list[str]:
    sensitive: list[str] = []
    for item in files:
        current = str(item.get("filename") or "")
        previous = str(item.get("previous_filename") or "")
        paths = [path for path in (current, previous) if path]
        patch = str(item.get("patch") or "")
        if any(_path_requires_human_approval(path) for path in paths) or (
            _patch_contains_sensitive_information(patch)
        ):
            sensitive.append(current or previous)
    return sensitive


def _is_authorized_autonomous_repair(
    pull_request: dict[str, Any],
    files: list[dict[str, Any]],
) -> bool:
    """Ordinary repairs are autonomous, including repairs originating from forks."""

    state = str(pull_request.get("state") or "open").lower()
    return state == "open" and bool(files) and not _high_risk_files(files)


def _pull_request_files(bot: AmosclaudBot, number: int) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for page in range(1, 51):
        result = bot._request(
            "GET",
            f"/repos/{bot.repository}/pulls/{number}/files?per_page=100&page={page}",
        )
        if not isinstance(result, list):
            return []
        files.extend(item for item in result if isinstance(item, dict))
        if len(result) < 100:
            return files
    return files


def handle_approval_event(
    bot: AmosclaudBot,
    payload: dict[str, Any],
    event_name: str,
) -> int | None:
    if event_name == "issue_comment":
        comment = payload.get("comment") or {}
        raw = str(comment.get("body") or "")
        command, objective = parse_command(raw)
        normalized = " ".join(raw.strip().split()).lower()
        association = str(comment.get("author_association") or "NONE").upper()

        if normalized.startswith("@amosclaud approve") or normalized.startswith(
            "@amosclaud-bot approve"
        ):
            return _record_decision(bot, payload, "approve")
        if normalized.startswith("@amosclaud deny") or normalized.startswith("@amosclaud-bot deny"):
            return _record_decision(bot, payload, "deny")

        if command == "fix" and _is_sensitive_objective(objective):
            issue = payload.get("issue") or {}
            source_number = issue.get("number", "unknown")
            if not isinstance(source_number, int):
                return 0

            if association not in WRITE_ASSOCIATIONS:
                bot.post_comment(
                    source_number,
                    "### Amosclaud Bot — Sensitive repair blocked\n"
                    "Only OWNER, MEMBER, or COLLABORATOR may authorize a repair "
                    "that handles environment secrets or personal information.",
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
                    source_number,
                    f"### Amosclaud Bot — Approval verified\n"
                    f"Approval issue #{approved} authorizes this one sensitive execution. "
                    "Proceeding with Amosclaud-Fixer.",
                )
                return None

            approval_number = _create_approval_issue(
                bot,
                source=_approval_source(source_number, objective),
                title=f"Sensitive Amosclaud-Fixer request from #{source_number}",
                reason_lines=[
                    "The requested repair handles an environment secret or personal information."
                ],
                requested_capability="Amosclaud-Fixer sensitive-data repair",
            )
            bot.post_comment(
                source_number,
                "### Amosclaud Bot — Human approval required\n"
                "The requested repair handles an environment secret or personal information. "
                f"Approval issue: #{approval_number}",
            )
            return 0

        return None

    if event_name == "pull_request":
        pull_request = payload.get("pull_request") or {}
        number = pull_request.get("number") or payload.get("number")
        if not isinstance(number, int):
            return None
        files = _pull_request_files(bot, number)
        sensitive = _high_risk_files(files)
        if not sensitive:
            return None

        approval_number = _create_approval_issue(
            bot,
            source=f"pull-request-{number}",
            title=f"Sensitive data changes in PR #{number}",
            reason_lines=[
                f"Environment, secret-bearing, or personal-information content detected: `{name}`"
                for name in sensitive[:12]
            ],
            requested_capability="Pull request repair or publication",
        )
        bot.post_comment(
            number,
            "### Amosclaud Bot — Human approval required\n"
            "Environment, secret-bearing, or personal-information content was detected. "
            f"Approval issue: #{approval_number}",
        )
        return 0

    return None
