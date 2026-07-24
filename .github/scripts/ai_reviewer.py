"""Deterministic pull-request feedback for Amosclaud.

This reviewer intentionally does not depend on an external AI provider. It reads
``pr_diff.txt``, detects high-signal risks, and posts one concise PR comment.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from github import Github

DIFF_PATH = Path(os.getenv("DIFF_PATH", "pr_diff.txt"))
MAX_DIFF_BYTES = 2_000_000


def review_diff(diff: str) -> list[str]:
    findings: list[str] = []
    added = "\n".join(
        line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")
    )
    lowered = added.lower()

    secret_patterns = [
        r"(?i)(api[_-]?key|secret|password|token)\s*=\s*['\"][^'\"]{8,}['\"]",
        r"(?i)authorization\s*[:=]\s*['\"]bearer\s+[^'\"]+['\"]",
    ]
    if any(re.search(pattern, added) for pattern in secret_patterns):
        findings.append("Potential hard-coded credential or bearer token was added; move it to environment-managed secrets.")

    if "response.json()" in added and "content-type" not in lowered:
        findings.append("A response is parsed as JSON without checking its content type; plain-text server errors could crash the client.")

    if "subprocess" in lowered or "os.system(" in lowered or "shell=true" in lowered:
        findings.append("Command execution changed; validate that user-controlled input cannot reach shell arguments unsafely.")

    if "../" in added or "path(" in lowered or "write_bytes" in lowered or "write_text" in lowered:
        if "resolve()" not in added and "safe" not in lowered:
            findings.append("Filesystem handling changed; verify path traversal protection and ownership checks.")

    if "delete" in lowered and ("account" in lowered or "user" in lowered):
        findings.append("Account/user deletion changed; verify confirmation, session invalidation, foreign-key cleanup, and irreversible-data messaging.")

    if "@router" in added or "app.include_router" in added:
        if "depends(" not in lowered and "cookie(" not in lowered and "x-api-key" not in lowered:
            findings.append("A new API route may lack explicit authentication or authorization; confirm access control is intentional.")

    if "android" in diff.lower() and "test" not in diff.lower():
        findings.append("Android code changed without an obvious matching test change; ensure the APK workflow covers compilation and unit tests.")

    return findings


def build_comment(findings: list[str]) -> str:
    if not findings:
        return (
            "### Amosclaud automated review\n\n"
            "No high-signal security, reliability, or test risks were detected in this diff. "
            "This is a lightweight automated check and does not replace human review."
        )
    bullets = "\n".join(f"- {finding}" for finding in findings)
    return (
        "### Amosclaud automated review\n\n"
        f"{bullets}\n\n"
        "Please confirm these items before merging. This deterministic review does not send code to an external AI provider."
    )


def main() -> None:
    repo_name = os.environ["REPO_NAME"]
    pr_number = int(os.environ["PR_NUMBER"])
    token = os.environ["GITHUB_TOKEN"]

    if not DIFF_PATH.exists():
        raise SystemExit(f"Diff file not found: {DIFF_PATH}")
    if DIFF_PATH.stat().st_size > MAX_DIFF_BYTES:
        diff = DIFF_PATH.read_text(encoding="utf-8", errors="replace")[:MAX_DIFF_BYTES]
    else:
        diff = DIFF_PATH.read_text(encoding="utf-8", errors="replace")

    comment = build_comment(review_diff(diff))
    Github(token).get_repo(repo_name).get_pull(pr_number).create_issue_comment(comment)
    print(comment)


if __name__ == "__main__":
    main()
