from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .bot import WRITE_ASSOCIATIONS, AmosclaudBot, parse_command, run_from_environment
from .execution_dashboard import TestCard, publish_dashboard, render_dashboard

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
SECURITY_HINTS = ("security", "auth", "permission", "token", "secret", "credential")
TEST_HINTS = ("test_", "_test.", "/tests/", "tests/")


def _changed_file_summary(files: list[dict[str, Any]]) -> dict[str, Any]:
    names = [str(item.get("filename") or "") for item in files if item.get("filename")]
    additions = sum(int(item.get("additions") or 0) for item in files)
    deletions = sum(int(item.get("deletions") or 0) for item in files)
    changed_lines = additions + deletions

    high_risk = [
        name
        for name in names
        if name in HIGH_RISK_FILES or any(name.startswith(prefix) for prefix in HIGH_RISK_PREFIXES)
    ]
    security_related = [
        name for name in names if any(hint in name.lower() for hint in SECURITY_HINTS)
    ]
    tests = [name for name in names if any(hint in name.lower() for hint in TEST_HINTS)]
    source_changes = [
        name
        for name in names
        if name.endswith((".py", ".js", ".ts", ".tsx", ".go", ".rs", ".java")) and name not in tests
    ]

    return {
        "names": names,
        "additions": additions,
        "deletions": deletions,
        "changed_lines": changed_lines,
        "high_risk": high_risk,
        "security_related": security_related,
        "tests": tests,
        "source_changes": source_changes,
    }


def _professional_review(
    *,
    pr: dict[str, Any],
    files: list[dict[str, Any]],
    autonomous_result: dict[str, Any],
) -> str:
    summary = _changed_file_summary(files)
    high: list[str] = []
    medium: list[str] = []
    low: list[str] = []

    if summary["high_risk"]:
        high.append(
            "High-risk repository or deployment files changed: "
            + ", ".join(f"`{name}`" for name in summary["high_risk"][:8])
        )
    if summary["security_related"]:
        high.append(
            "Security/authentication-sensitive paths changed: "
            + ", ".join(f"`{name}`" for name in summary["security_related"][:8])
        )
    if summary["source_changes"] and not summary["tests"]:
        medium.append(
            "Source code changed, but no changed test file was detected in this pull request."
        )
    if summary["changed_lines"] > 800:
        medium.append(
            f"Large change set detected ({summary['changed_lines']} changed lines); split or perform focused human review."
        )
    if not high and not medium:
        low.append(
            "No high-risk path or missing-test signal was detected by the deterministic baseline review."
        )

    autonomous_status = str(autonomous_result.get("status") or "unknown").upper()
    evidence = [str(item) for item in (autonomous_result.get("evidence") or [])][:5]
    if autonomous_status not in {"SUCCESS", "COMPLETED", "READY"}:
        medium.append(
            f"Autonomous review runtime returned `{autonomous_status}`; human verification is required."
        )

    recommendation = (
        "CHANGES REQUESTED" if high else ("NEEDS HUMAN REVIEW" if medium else "APPROVE")
    )
    risk = "HIGH" if high else ("MEDIUM" if medium else "LOW")
    title = str(pr.get("title") or "Untitled pull request")
    base = str((pr.get("base") or {}).get("ref") or "unknown")
    head = str((pr.get("head") or {}).get("ref") or "unknown")

    def section(items: list[str]) -> str:
        return (
            "\n".join(f"- {item}" for item in items)
            if items
            else "- None detected by this baseline review."
        )

    tests_text = (
        f"Changed test files detected: {len(summary['tests'])}."
        if summary["tests"]
        else "No changed test file detected."
    )
    security_text = (
        "Sensitive path changes require focused review before merge."
        if summary["high_risk"] or summary["security_related"]
        else "No sensitive path change detected by filename/path policy."
    )

    body = (
        "### Amosclaud Bot — Professional PR Review\n\n"
        "**Engine:** Amosclaud Autonomous\n"
        f"**Autonomous status:** **{autonomous_status}**\n"
        f"**Risk:** **{risk}**\n\n"
        "## Summary\n"
        f"- **PR:** {title}\n"
        f"- **Branch:** `{head}` → `{base}`\n"
        f"- **Files changed:** {len(summary['names'])}\n"
        f"- **Diff size:** +{summary['additions']} / -{summary['deletions']}\n\n"
        "## Findings\n\n"
        "### HIGH\n"
        f"{section(high)}\n\n"
        "### MEDIUM\n"
        f"{section(medium)}\n\n"
        "### LOW\n"
        f"{section(low)}\n\n"
        "## Security\n"
        f"- {security_text}\n\n"
        "## Tests\n"
        f"- {tests_text}\n\n"
        "## Code quality\n"
        "- Review is read-only; repository writes remain restricted to trusted `@amosclaud fix ...` requests.\n"
    )
    if evidence:
        body += "\n## Autonomous evidence\n" + "\n".join(f"- {item}" for item in evidence) + "\n"
    body += (
        "\n## Recommendation\n"
        f"**{recommendation}**\n\n"
        "Recommended next command: `@amosclaud fix <specific problem>` only for a targeted, trusted repair."
    )
    return body[:10000]


def _handle_professional_review(payload: dict[str, Any]) -> int | None:
    comment = payload.get("comment") or {}
    command, objective = parse_command(str(comment.get("body") or ""))
    issue = payload.get("issue") or {}
    if command != "review" or not issue.get("pull_request"):
        return None

    number = int(issue["number"])
    repository = os.getenv("GITHUB_REPOSITORY", "")
    token = os.getenv("GITHUB_TOKEN", "")
    if not repository or not token:
        raise RuntimeError(
            "GITHUB_REPOSITORY and GITHUB_TOKEN are required for professional PR review"
        )

    bot = AmosclaudBot(repository=repository, token=token, workspace=Path.cwd())
    pr = bot._request("GET", f"/repos/{repository}/pulls/{number}")
    files = bot._request("GET", f"/repos/{repository}/pulls/{number}/files?per_page=100")
    if not isinstance(files, list):
        files = []

    review_objective = (
        objective
        or f"Review pull request #{number} for correctness, tests, security, and merge risk"
    )
    autonomous_result = bot._run_local("review", review_objective, allow_writes=False)
    body = _professional_review(pr=pr, files=files, autonomous_result=autonomous_result)
    bot.post_comment(number, body)
    return 0


def _trusted_fix(payload: dict[str, Any]) -> tuple[bool, str, int]:
    comment = payload.get("comment") or {}
    command, objective = parse_command(str(comment.get("body") or ""))
    association = str(comment.get("author_association") or "NONE").upper()
    number = (payload.get("issue") or {}).get("number")
    return (
        command == "fix" and association in WRITE_ASSOCIATIONS and isinstance(number, int),
        objective,
        int(number) if isinstance(number, int) else 0,
    )


def _prepare_new_files_for_diff(workspace: Path) -> list[str]:
    """Make safe untracked files visible to ``git diff`` using intent-to-add.

    The publication workflow historically checked only ``git diff``. New files
    created by Autonomous are untracked, so they were incorrectly reported as
    "NO CHANGES". Intent-to-add preserves the review boundary without staging
    content or committing anything.
    """
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=workspace,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        return []
    candidates = [
        item.decode("utf-8", errors="replace") for item in result.stdout.split(b"\0") if item
    ]
    safe = [
        path
        for path in candidates
        if path not in HIGH_RISK_FILES
        and not path.startswith((".git/", ".amosclaud/", *HIGH_RISK_PREFIXES))
    ]
    if safe:
        subprocess.run(
            ["git", "add", "--intent-to-add", "--", *safe],
            cwd=workspace,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    return safe


def _has_diff(workspace: Path) -> bool:
    unstaged = subprocess.run(["git", "diff", "--quiet"], cwd=workspace, check=False)
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=workspace, check=False)
    return unstaged.returncode != 0 or staged.returncode != 0


def _publish_no_change_dashboard(payload: dict[str, Any], objective: str, number: int) -> None:
    repository = os.getenv("GITHUB_REPOSITORY", "")
    token = os.getenv("GITHUB_TOKEN", "")
    if not repository or not token or not number:
        return
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=Path.cwd(),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ).stdout.strip()
    body = render_dashboard(
        objective=objective or "Repository engineering task",
        current_stage="edit",
        outcome="failed",
        tests=[
            TestCard(
                "Repository change production",
                "failed",
                "The execution runtime returned without a safe file proposal. Review the preceding Amosclaud result for the exact blocker.",
            ),
            TestCard(
                "Truth gate",
                "passed",
                "No commit or pull request was claimed without a real changed file.",
            ),
        ],
        branch=branch,
    )
    publish_dashboard(AmosclaudBot(repository, token=token), number, body)


def run_professional_from_environment() -> int:
    event_name = os.getenv("GITHUB_EVENT_NAME", "")
    event_path = os.getenv("GITHUB_EVENT_PATH", "")
    payload: dict[str, Any] | None = None
    if event_name == "issue_comment" and event_path:
        payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
        handled = _handle_professional_review(payload)
        if handled is not None:
            return handled

    result = run_from_environment()

    if payload is not None:
        trusted, objective, number = _trusted_fix(payload)
        if trusted:
            workspace = Path.cwd()
            _prepare_new_files_for_diff(workspace)
            if not _has_diff(workspace):
                _publish_no_change_dashboard(payload, objective, number)
    return result


if __name__ == "__main__":
    raise SystemExit(run_professional_from_environment())
