"""Dispatch bounded same-PR repair callbacks from failed GitHub Actions runs.

This module is intentionally independent from pull-request code. It runs from the
trusted default-branch workflow after a ``workflow_run`` event, validates that the
failed run belongs to an open same-repository pull request, deduplicates callbacks
by head SHA, and asks Amosclaud to repair the exact failure on the existing branch.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request

ALLOWED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
HEAD_MARKER_PREFIX = "<!-- amosclaud-self-heal:"
ATTEMPT_MARKER_PREFIX = "<!-- amosclaud-self-heal-attempt:"
DEFAULT_MAX_ATTEMPTS = 5
MAX_LOG_CHARS = 12_000
ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str
    pr_number: int | None = None
    attempt: int = 0
    body: str = ""


class GitHubClient:
    """Minimal GitHub REST client used by the trusted callback workflow."""

    def __init__(self, repository: str, token: str, api_url: str = "https://api.github.com") -> None:
        self.repository = repository
        self.token = token
        self.api_url = api_url.rstrip("/")

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        accept: str = "application/vnd.github+json",
    ) -> Any:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.api_url}{path}",
            data=data,
            method=method,
            headers={
                "Accept": accept,
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "amosclaud-self-healing-pr-loop",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with request.urlopen(req, timeout=30) as response:
                raw = response.read()
        except error.HTTPError as exc:  # pragma: no cover - exercised by live workflow
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub API {method} {path} failed: {exc.code}: {detail}") from exc
        return json.loads(raw.decode("utf-8")) if raw else None

    def pull_requests_for_commit(self, head_sha: str) -> list[dict[str, Any]]:
        result = self._request(
            "GET",
            f"/repos/{self.repository}/commits/{head_sha}/pulls",
            accept="application/vnd.github+json",
        )
        return result if isinstance(result, list) else []

    def pull_request(self, number: int) -> dict[str, Any]:
        result = self._request("GET", f"/repos/{self.repository}/pulls/{number}")
        if not isinstance(result, dict):
            raise RuntimeError("GitHub returned an invalid pull-request payload")
        return result

    def comments(self, number: int) -> list[dict[str, Any]]:
        result = self._request(
            "GET",
            f"/repos/{self.repository}/issues/{number}/comments?per_page=100",
        )
        return result if isinstance(result, list) else []

    def post_comment(self, number: int, body: str) -> None:
        self._request(
            "POST",
            f"/repos/{self.repository}/issues/{number}/comments",
            {"body": body},
        )


def _clean_log(raw: str) -> str:
    text = ANSI_ESCAPE.sub("", raw.replace("\x00", ""))
    text = text.replace("```", "` ` `").strip()
    if not text:
        return "GitHub did not expose a failed-log body. Inspect the linked workflow run."
    if len(text) > MAX_LOG_CHARS:
        text = "[log tail truncated]\n" + text[-MAX_LOG_CHARS:]
    return text


def _comment_bodies(comments: list[dict[str, Any]]) -> list[str]:
    return [str(comment.get("body") or "") for comment in comments]


def _attempt_count(comments: list[dict[str, Any]]) -> int:
    return sum(body.count(ATTEMPT_MARKER_PREFIX) for body in _comment_bodies(comments))


def _pr_number_from_event(event: dict[str, Any]) -> int | None:
    run = event.get("workflow_run") or {}
    pull_requests = run.get("pull_requests") or []
    for item in pull_requests:
        number = item.get("number") if isinstance(item, dict) else None
        if isinstance(number, int) and number > 0:
            return number
    return None


def build_decision(
    *,
    event: dict[str, Any],
    repository: str,
    pull_request: dict[str, Any],
    comments: list[dict[str, Any]],
    failed_log: str,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> Decision:
    """Return a callback, blocker, or no-op decision without performing I/O."""

    run = event.get("workflow_run") or {}
    conclusion = str(run.get("conclusion") or "")
    run_event = str(run.get("event") or "")
    head_sha = str(run.get("head_sha") or "")
    head_branch = str(run.get("head_branch") or "")
    head_repository = str(((run.get("head_repository") or {}).get("full_name") or ""))
    workflow_name = str(run.get("name") or "Unknown workflow")
    workflow_url = str(run.get("html_url") or "")
    pr_number = int(pull_request.get("number") or 0) or None

    if conclusion != "failure":
        return Decision("noop", "workflow_did_not_fail", pr_number)
    if run_event != "pull_request":
        return Decision("noop", "not_a_pull_request_run", pr_number)
    if not head_sha or head_repository != repository:
        return Decision("noop", "untrusted_or_missing_head_repository", pr_number)
    if str(pull_request.get("state") or "") != "open":
        return Decision("noop", "pull_request_not_open", pr_number)

    pr_head = pull_request.get("head") or {}
    pr_head_repo = str(((pr_head.get("repo") or {}).get("full_name") or ""))
    if str(pr_head.get("sha") or "") != head_sha or pr_head_repo != repository:
        return Decision("noop", "pull_request_head_moved_or_is_external", pr_number)
    if str(pull_request.get("author_association") or "") not in ALLOWED_ASSOCIATIONS:
        return Decision("noop", "pull_request_author_not_trusted", pr_number)

    marker = f"{HEAD_MARKER_PREFIX}{head_sha} -->"
    bodies = _comment_bodies(comments)
    if any(marker in body for body in bodies):
        return Decision("noop", "callback_already_dispatched_for_head", pr_number)

    attempt = _attempt_count(comments) + 1
    bounded_max = max(1, min(int(max_attempts), 5))
    if attempt > bounded_max:
        body = (
            f"{marker}\n"
            "### Amosclaud self-healing loop — human action required\n\n"
            f"The same pull request reached the bounded limit of **{bounded_max}** automated "
            "repair callbacks. Amosclaud is stopping instead of looping indefinitely or claiming "
            "success. Review the linked failing workflow and provide credentials, approval, "
            "external-service access, or a broader design decision if required.\n\n"
            f"- **Failed workflow:** `{workflow_name}`\n"
            f"- **Head:** `{head_sha}`\n"
            f"- **Run:** {workflow_url or 'unavailable'}"
        )
        return Decision("block", "repair_attempt_limit_reached", pr_number, attempt, body)

    clean_log = _clean_log(failed_log)
    body = (
        "@amosclaud fix the failing GitHub Actions checks on this same pull-request branch. "
        "Use the exact failed evidence below, diagnose the root cause, edit only the responsible "
        "code or tests, run focused verification and the repository verification, then commit the "
        "verified correction back to this PR. Do not merge. Do not report success while any "
        "required GitHub Actions check is failing.\n\n"
        f"{marker}\n"
        f"{ATTEMPT_MARKER_PREFIX}{attempt} -->\n"
        "### Automatic same-PR repair callback\n\n"
        f"- **Attempt:** `{attempt}/{bounded_max}`\n"
        f"- **Failed workflow:** `{workflow_name}`\n"
        f"- **Branch:** `{head_branch}`\n"
        f"- **Head:** `{head_sha}`\n"
        f"- **Run:** {workflow_url or 'unavailable'}\n\n"
        "#### Exact failed-log tail\n\n"
        f"```text\n{clean_log}\n```\n\n"
        "A new repair commit must cause a fresh full Actions matrix. If the new matrix fails, the "
        "callback loop may run again on the new head until it becomes green or reaches a verified "
        "human-only blocker."
    )
    return Decision("callback", "trusted_failed_pr_run", pr_number, attempt, body)


def _resolve_pull_request(
    client: GitHubClient,
    event: dict[str, Any],
) -> dict[str, Any] | None:
    number = _pr_number_from_event(event)
    if number is not None:
        return client.pull_request(number)
    run = event.get("workflow_run") or {}
    head_sha = str(run.get("head_sha") or "")
    if not head_sha:
        return None
    candidates = client.pull_requests_for_commit(head_sha)
    for candidate in candidates:
        if candidate.get("state") == "open":
            return client.pull_request(int(candidate["number"]))
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", default=os.getenv("GITHUB_EVENT_PATH", ""))
    parser.add_argument("--failed-log", required=True)
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=int(os.getenv("AMOSCLAUD_MAX_PR_REPAIR_ATTEMPTS", DEFAULT_MAX_ATTEMPTS)),
    )
    args = parser.parse_args()

    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    token = os.environ.get("AMOSCLAUD_GITHUB_TOKEN", "").strip()
    if not repository or not token or not args.event:
        raise SystemExit("GITHUB_REPOSITORY, AMOSCLAUD_GITHUB_TOKEN, and event path are required")

    event = json.loads(Path(args.event).read_text(encoding="utf-8"))
    failed_log = Path(args.failed_log).read_text(encoding="utf-8", errors="replace")
    client = GitHubClient(repository, token, os.getenv("GITHUB_API_URL", "https://api.github.com"))
    pull_request = _resolve_pull_request(client, event)
    if pull_request is None:
        print(json.dumps({"action": "noop", "reason": "no_open_pull_request"}))
        return 0

    number = int(pull_request["number"])
    comments = client.comments(number)
    decision = build_decision(
        event=event,
        repository=repository,
        pull_request=pull_request,
        comments=comments,
        failed_log=failed_log,
        max_attempts=args.max_attempts,
    )
    if decision.action in {"callback", "block"}:
        client.post_comment(number, decision.body)
    print(json.dumps(decision.__dict__, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
