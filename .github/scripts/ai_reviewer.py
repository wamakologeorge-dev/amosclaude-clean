"""Deterministic pull-request feedback for Amosclaud.

This reviewer intentionally does not depend on an external AI provider. It reads
``pr_diff.txt``, detects high-signal risks, and keeps one concise PR comment up to
date instead of creating duplicate comments after every synchronize event.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable

from github import Github

DIFF_PATH = Path(os.getenv("DIFF_PATH", "pr_diff.txt"))
MAX_DIFF_BYTES = 2_000_000
COMMENT_MARKER = "<!-- amosclaud-automated-review -->"
COMMENT_HEADING = "### Amosclaud automated review"

_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|client[_-]?secret|secret|password|token)[a-z0-9_-]*"
    r"\s*=\s*(['\"])([^'\"]+)\1"
)
_BEARER_LITERAL = re.compile(
    r"(?i)\bauthorization\s*[:=]\s*(['\"])bearer\s+([^'\"]+)\1"
)
_PLACEHOLDER_MARKERS = (
    "example",
    "dummy",
    "fake",
    "masked",
    "placeholder",
    "sample",
    "test-token",
    "test_key",
    "test-key",
)
_KNOWN_SECRET_PREFIXES = (
    "github_pat_",
    "ghp_",
    "gho_",
    "ghu_",
    "ghs_",
    "ghr_",
    "sk-",
    "xoxb-",
    "xoxp-",
)


def _looks_like_literal_secret(value: str) -> bool:
    candidate = value.strip()
    lowered = candidate.lower()
    if not candidate or any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
        return False
    if candidate.startswith(("${{", "$", "{{")) or "secrets." in lowered:
        return False
    if lowered.startswith(_KNOWN_SECRET_PREFIXES):
        return len(candidate) >= 16
    if len(candidate) < 24 or any(character.isspace() for character in candidate):
        return False
    classes = sum(
        (
            any(character.islower() for character in candidate),
            any(character.isupper() for character in candidate),
            any(character.isdigit() for character in candidate),
            any(not character.isalnum() for character in candidate),
        )
    )
    return classes >= 3


def _added_text(diff: str) -> str:
    return "\n".join(
        line[1:]
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


def _contains_literal_secret(added: str) -> bool:
    for match in _SECRET_ASSIGNMENT.finditer(added):
        if _looks_like_literal_secret(match.group(2)):
            return True
    for match in _BEARER_LITERAL.finditer(added):
        if _looks_like_literal_secret(match.group(2)):
            return True
    return False


def _contains_shell_execution(added: str) -> bool:
    patterns = (
        r"\bos\.system\s*\(",
        r"\bshell\s*=\s*true\b",
        r"\bsubprocess\.(?:run|popen|call|check_call|check_output)\s*\("
        r".{0,1200}?\bshell\s*=\s*true\b",
        r"\bsubprocess\.(?:run|popen|call|check_call|check_output)\s*\("
        r".{0,400}?\[\s*['\"](?:ba|z|da|a)?sh['\"]\s*,\s*['\"]-c['\"]",
    )
    return any(
        re.search(pattern, added, re.IGNORECASE | re.DOTALL)
        for pattern in patterns
    )


def review_diff(diff: str) -> list[str]:
    findings: list[str] = []
    added = _added_text(diff)
    lowered = added.lower()

    if _contains_literal_secret(added):
        findings.append(
            "Potential hard-coded credential or bearer token was added; "
            "move it to environment-managed secrets."
        )

    if "response.json()" in added and "content-type" not in lowered:
        findings.append(
            "A response is parsed as JSON without checking its content type; "
            "plain-text server errors could crash the client."
        )

    if _contains_shell_execution(added):
        findings.append(
            "Shell-based command execution changed; validate that "
            "user-controlled input cannot reach the shell."
        )

    if (
        "../" in added
        or "path(" in lowered
        or "write_bytes" in lowered
        or "write_text" in lowered
    ):
        if "resolve()" not in added and "safe" not in lowered:
            findings.append(
                "Filesystem handling changed; verify path traversal protection "
                "and ownership checks."
            )

    if "delete" in lowered and ("account" in lowered or "user" in lowered):
        findings.append(
            "Account/user deletion changed; verify confirmation, session "
            "invalidation, foreign-key cleanup, and irreversible-data messaging."
        )

    if "@router" in added or "app.include_router" in added:
        if (
            "depends(" not in lowered
            and "cookie(" not in lowered
            and "x-api-key" not in lowered
        ):
            findings.append(
                "A new API route may lack explicit authentication or authorization; "
                "confirm access control is intentional."
            )

    if "android" in diff.lower() and "test" not in diff.lower():
        findings.append(
            "Android code changed without an obvious matching test change; "
            "ensure the APK workflow covers compilation and unit tests."
        )

    return findings


def build_comment(findings: list[str]) -> str:
    prefix = f"{COMMENT_MARKER}\n{COMMENT_HEADING}\n\n"
    if not findings:
        return (
            prefix
            + "No high-signal security, reliability, or test risks were detected "
            "in this diff. This is a lightweight automated check and does not "
            "replace human review."
        )
    bullets = "\n".join(f"- {finding}" for finding in findings)
    return (
        prefix
        + f"{bullets}\n\n"
        + "Please confirm these items before merging. This deterministic review "
        "does not send code to an external AI provider."
    )


def publish_comment(pull: Any, comment: str) -> None:
    existing = [
        item
        for item in pull.get_issue_comments()
        if COMMENT_MARKER in str(getattr(item, "body", ""))
        or str(getattr(item, "body", "")).startswith(COMMENT_HEADING)
    ]
    if not existing:
        pull.create_issue_comment(comment)
        return

    canonical = existing[-1]
    try:
        canonical.edit(comment)
        duplicates = existing[:-1]
    except Exception as exc:
        # A repository PAT cannot edit a comment authored by github-actions[bot].
        # Create a token-owned canonical comment, then remove old cards best-effort.
        print(f"Could not edit prior review comment: {type(exc).__name__}")
        pull.create_issue_comment(comment)
        duplicates = existing

    for duplicate in duplicates:
        try:
            duplicate.delete()
        except Exception as exc:
            # Cleanup is best-effort; the canonical review is still valid.
            print(f"Could not remove duplicate review comment: {type(exc).__name__}")


def publish_with_tokens(
    repo_name: str,
    pr_number: int,
    comment: str,
    tokens: list[str],
    *,
    github_factory: Callable[[str], Any] = Github,
) -> bool:
    """Publish with the broad Amosclaud token, then the scoped Actions token.

    Review analysis remains authoritative even when GitHub comment delivery is
    temporarily unavailable. Tokens are never printed and duplicate values are
    attempted only once.
    """

    attempted: set[str] = set()
    for token in tokens:
        candidate = str(token or "").strip()
        if not candidate or candidate in attempted:
            continue
        attempted.add(candidate)
        try:
            pull = github_factory(candidate).get_repo(repo_name).get_pull(pr_number)
            publish_comment(pull, comment)
            return True
        except Exception as exc:
            print(f"Review delivery attempt failed: {type(exc).__name__}")
    return False


def main() -> None:
    repo_name = os.environ["REPO_NAME"]
    pr_number = int(os.environ["PR_NUMBER"])

    if not DIFF_PATH.exists():
        raise SystemExit(f"Diff file not found: {DIFF_PATH}")
    if DIFF_PATH.stat().st_size > MAX_DIFF_BYTES:
        diff = DIFF_PATH.read_text(encoding="utf-8", errors="replace")[:MAX_DIFF_BYTES]
    else:
        diff = DIFF_PATH.read_text(encoding="utf-8", errors="replace")

    comment = build_comment(review_diff(diff))
    delivered = publish_with_tokens(
        repo_name,
        pr_number,
        comment,
        [
            os.getenv("AMOSCLAUD_GITHUB_TOKEN", ""),
            os.getenv("GITHUB_FALLBACK_TOKEN", ""),
            os.getenv("GITHUB_TOKEN", ""),
        ],
    )
    if not delivered:
        print("Review comment delivery was unavailable; review evidence follows.")
    print(comment)


if __name__ == "__main__":
    main()
