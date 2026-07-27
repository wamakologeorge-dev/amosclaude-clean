#!/usr/bin/env python3
"""Re-enter a blocked Amosclaud PR repair with exact, bounded evidence.

The primary repair control plane owns diagnosis, candidate generation, isolated
verification, and publication. This companion activates only after that control
plane records a pull-request incident as ``blocked``. It posts a new authorized
``@amosclaud fix`` command on the same PR, carrying the exact failed-check and
repair-run evidence. A scheduled sweep retries stalled callbacks after a
cooldown, while per-revision limits and stale-head checks prevent infinite loops
or writes to a branch that has moved.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

INCIDENT_PREFIX = "[Amosclaud Repair Incident "
BLOCKED_MARKER = "<!-- amosclaud-repair-state:blocked -->"
INCIDENT_RE = re.compile(r"<!-- amosclaud-repair-incident:([0-9a-f]{16,32}) -->")
ACTION_RUN_RE = re.compile(r"/actions/runs/(\d+)")
CALLBACK_RE = re.compile(
    r"<!-- amosclaud-repair-callback:([0-9a-f]{16,32}):([0-9a-f]{40}):attempt-(\d+) -->"
)
FIELD_PATTERNS = {
    "state": re.compile(r"- State: \*\*([^*]+)\*\*"),
    "route": re.compile(r"- Route: `([^`]+)`"),
    "provider": re.compile(r"- Provider: `([^`]+)`"),
    "source": re.compile(r"- Source: `([^`]+)`"),
    "target_sha": re.compile(r"- Target revision: `([0-9a-f]{40})`"),
    "target_branch": re.compile(r"- Target branch: `([^`]+)`"),
    "pull_request": re.compile(r"- Pull request: `([^`]+)`"),
    "attempts": re.compile(r"- Attempts: `([0-9]+)`"),
}
FAILURE_CONCLUSIONS = {"failure", "timed_out", "action_required", "startup_failure"}
SUCCESS_CONCLUSIONS = {"success", "neutral", "skipped"}
REDACTION_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"amos_(?:svc|agent|auto)_[A-Za-z0-9_-]{16,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(
        r"(?i)\b(api[_-]?key|token|secret|password|authorization)\s*[:=]\s*[^\s]+"
    ),
)


@dataclass(frozen=True)
class Incident:
    number: int
    fingerprint: str
    state: str
    route: str
    provider: str
    source: str
    target_sha: str
    target_branch: str
    pull_request: int
    repair_attempts: int
    body: str


@dataclass(frozen=True)
class RetryDecision:
    allowed: bool
    reason: str
    next_attempt: int


def redact(value: str) -> str:
    text = str(value)
    for pattern in REDACTION_PATTERNS[:3]:
        text = pattern.sub("[REDACTED]", text)
    text = REDACTION_PATTERNS[3].sub(
        lambda match: f"{match.group(1)}=[REDACTED]", text
    )
    return text


def safe_markdown(value: str, limit: int = 12_000) -> str:
    """Bound untrusted evidence and prevent mentions/HTML comment injection."""
    text = redact(value).replace("\x00", "")
    text = text.replace("<!--", "< !--").replace("-->", "-- >")
    text = text.replace("@", "@\u200b")
    if len(text) > limit:
        text = "...[earlier evidence truncated]...\n" + text[-limit:]
    return text


def _request(
    method: str,
    url: str,
    *,
    token: str,
    payload: dict[str, Any] | None = None,
    accept: str = "application/vnd.github+json",
) -> bytes:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": accept,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Amosclaud-Repair-Callback/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GitHub API {method} {url} failed: HTTP {error.code}: "
            f"{safe_markdown(detail, 2_000)}"
        ) from error


def _json(
    method: str,
    url: str,
    *,
    token: str,
    payload: dict[str, Any] | None = None,
    accept: str = "application/vnd.github+json",
) -> Any:
    body = _request(method, url, token=token, payload=payload, accept=accept)
    return json.loads(body.decode("utf-8")) if body else None


def _api(repository: str, suffix: str) -> str:
    return f"https://api.github.com/repos/{repository}{suffix}"


def _field(body: str, name: str, default: str = "") -> str:
    match = FIELD_PATTERNS[name].search(body)
    return match.group(1).strip() if match else default


def parse_incident(issue: dict[str, Any]) -> Incident | None:
    title = str(issue.get("title") or "")
    body = str(issue.get("body") or "")
    marker = INCIDENT_RE.search(body)
    if not title.startswith(INCIDENT_PREFIX) or not marker:
        return None
    pr_raw = _field(body, "pull_request")
    if not pr_raw.isdigit():
        return None
    attempts_raw = _field(body, "attempts", "0")
    return Incident(
        number=int(issue.get("number") or 0),
        fingerprint=marker.group(1),
        state=_field(body, "state").lower(),
        route=_field(body, "route").lower(),
        provider=_field(body, "provider").lower(),
        source=_field(body, "source"),
        target_sha=_field(body, "target_sha").lower(),
        target_branch=_field(body, "target_branch"),
        pull_request=int(pr_raw),
        repair_attempts=int(attempts_raw) if attempts_raw.isdigit() else 0,
        body=body,
    )


def callback_marker(incident: Incident, attempt: int) -> str:
    return (
        f"<!-- amosclaud-repair-callback:{incident.fingerprint}:"
        f"{incident.target_sha}:attempt-{attempt} -->"
    )


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def callback_history(
    comments: Iterable[dict[str, Any]], incident: Incident
) -> tuple[int, datetime | None]:
    maximum = 0
    latest: datetime | None = None
    for comment in comments:
        body = str(comment.get("body") or "")
        for fingerprint, sha, attempt_raw in CALLBACK_RE.findall(body):
            if fingerprint != incident.fingerprint or sha != incident.target_sha:
                continue
            maximum = max(maximum, int(attempt_raw))
            updated = _parse_time(str(comment.get("updated_at") or comment.get("created_at") or ""))
            if updated and (latest is None or updated > latest):
                latest = updated
    return maximum, latest


def retry_decision(
    *,
    completed_attempts: int,
    latest_attempt_at: datetime | None,
    now: datetime,
    max_attempts: int,
    cooldown_seconds: int,
) -> RetryDecision:
    if completed_attempts >= max_attempts:
        return RetryDecision(False, "callback attempt limit reached", completed_attempts)
    if latest_attempt_at is not None:
        elapsed = (now - latest_attempt_at).total_seconds()
        if elapsed < cooldown_seconds:
            remaining = max(1, int(cooldown_seconds - elapsed))
            return RetryDecision(False, f"callback cooldown active ({remaining}s remaining)", completed_attempts)
    return RetryDecision(True, "callback is eligible", completed_attempts + 1)


def _paged(repository: str, suffix: str, token: str, *, limit: int = 300) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page = 1
    separator = "&" if "?" in suffix else "?"
    while len(items) < limit:
        batch = _json(
            "GET",
            _api(repository, f"{suffix}{separator}per_page=100&page={page}"),
            token=token,
        )
        if not isinstance(batch, list) or not batch:
            break
        items.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < 100:
            break
        page += 1
    return items[:limit]


def _open_blocked_incidents(repository: str, token: str) -> list[dict[str, Any]]:
    query = urllib.parse.quote(
        f'repo:{repository} is:issue is:open in:title "Amosclaud Repair Incident"'
    )
    result = _json(
        "GET",
        f"https://api.github.com/search/issues?q={query}&per_page=100",
        token=token,
    )
    items = result.get("items", []) if isinstance(result, dict) else []
    return [item for item in items if isinstance(item, dict)]


def _check_state(repository: str, sha: str, token: str) -> tuple[bool, list[str], bool]:
    checks = _json(
        "GET",
        _api(repository, f"/commits/{sha}/check-runs?per_page=100"),
        token=token,
        accept="application/vnd.github+json",
    )
    statuses = _json("GET", _api(repository, f"/commits/{sha}/status"), token=token)
    check_runs = checks.get("check_runs", []) if isinstance(checks, dict) else []
    status_items = statuses.get("statuses", []) if isinstance(statuses, dict) else []
    failures: list[str] = []
    pending = False
    for item in check_runs:
        status = str(item.get("status") or "")
        conclusion = str(item.get("conclusion") or "")
        name = str(item.get("name") or "unnamed GitHub check")
        if status != "completed":
            pending = True
        elif conclusion in FAILURE_CONCLUSIONS:
            failures.append(f"{name}: {conclusion}")
        elif conclusion and conclusion not in SUCCESS_CONCLUSIONS:
            failures.append(f"{name}: {conclusion}")
    for item in status_items:
        state = str(item.get("state") or "")
        context = str(item.get("context") or "external status")
        if state == "pending":
            pending = True
        elif state in {"failure", "error"}:
            failures.append(f"{context}: {state}")
    green = bool(check_runs or status_items) and not failures and not pending
    return green, failures[:20], pending


def _decode_job_log(body: bytes) -> str:
    if body.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                values = []
                for name in archive.namelist()[:20]:
                    values.append(archive.read(name).decode("utf-8", errors="replace"))
                return "\n".join(values)
        except zipfile.BadZipFile:
            pass
    return body.decode("utf-8", errors="replace")


def _latest_repair_run(issue_comments: Iterable[dict[str, Any]]) -> int | None:
    found: list[int] = []
    for comment in issue_comments:
        for value in ACTION_RUN_RE.findall(str(comment.get("body") or "")):
            found.append(int(value))
    return found[-1] if found else None


def _repair_run_evidence(repository: str, run_id: int | None, token: str) -> str:
    if not run_id:
        return "No repair-control run URL was recorded in the incident comments."
    jobs = _json(
        "GET", _api(repository, f"/actions/runs/{run_id}/jobs?per_page=100"), token=token
    )
    job_items = jobs.get("jobs", []) if isinstance(jobs, dict) else []
    sections: list[str] = []
    for job in job_items[:8]:
        job_id = int(job.get("id") or 0)
        if not job_id:
            continue
        raw = _request(
            "GET",
            _api(repository, f"/actions/jobs/{job_id}/logs"),
            token=token,
            accept="application/vnd.github+json",
        )
        text = _decode_job_log(raw)
        markers = (
            "AMOSCLAUD_VERIFICATION_PASSED=false",
            "No repair was published",
            "candidate failed",
            "verification failed",
            "FAILED",
            "Error:",
        )
        position = max((text.lower().rfind(marker.lower()) for marker in markers), default=-1)
        excerpt = text[max(0, position - 5_000) : position + 7_000] if position >= 0 else text[-10_000:]
        sections.append(
            f"=== repair-control job: {job.get('name', job_id)} "
            f"({job.get('conclusion') or job.get('status')}) ===\n{excerpt}"
        )
    return safe_markdown("\n\n".join(sections) or "The repair-control run exposed no readable job log.", 18_000)


def build_command(
    incident: Incident,
    attempt: int,
    failures: list[str],
    evidence: str,
) -> str:
    failure_text = "\n".join(f"- {safe_markdown(item, 500)}" for item in failures)
    if not failure_text:
        failure_text = "- The repair incident remains blocked; reproduce the failing check before editing."
    marker = callback_marker(incident, attempt)
    return (
        "@amosclaud fix the unresolved GitHub Actions failures on this pull request. "
        "This is a corrective callback after a previous repair candidate failed or produced no "
        "verified change. Reproduce the current failure, diagnose the root cause from the exact "
        "evidence below, modify only the necessary code and regression tests, rerun focused and "
        "full verification, and commit the repair to this same PR branch. Do not merge the PR. "
        "Do not report success while any required check is red or pending.\n\n"
        f"{marker}\n"
        f"**Repair incident:** #{incident.number}  \n"
        f"**Callback attempt:** {attempt}  \n"
        f"**Target revision:** `{incident.target_sha}`  \n"
        f"**Failure source:** {safe_markdown(incident.source, 500)}\n\n"
        "### Current failing checks\n"
        f"{failure_text}\n\n"
        "### Exact previous repair evidence\n"
        "```text\n"
        f"{safe_markdown(evidence, 18_000)}\n"
        "```\n\n"
        "If your first correction fails verification, read the new compiler/test/build output, "
        "correct the failing code line, and rerun the same checks before publishing."
    )[:30_000]


def _post(repository: str, issue_number: int, body: str, token: str) -> dict[str, Any]:
    result = _json(
        "POST",
        _api(repository, f"/issues/{issue_number}/comments"),
        token=token,
        payload={"body": body},
    )
    return result if isinstance(result, dict) else {}


def process_incident(
    repository: str,
    issue: dict[str, Any],
    token: str,
    *,
    max_attempts: int,
    cooldown_seconds: int,
    now: datetime,
) -> tuple[bool, str]:
    incident = parse_incident(issue)
    if not incident:
        return False, "not an Amosclaud repair incident"
    if incident.state != "blocked" or BLOCKED_MARKER not in incident.body:
        return False, f"incident state is {incident.state or 'unknown'}, not blocked"
    if incident.route != "pull_request":
        return False, f"route {incident.route!r} is not a pull-request callback"
    if incident.provider not in {"github_actions", "manual"}:
        return False, f"provider {incident.provider!r} is report-only for code callbacks"

    pull = _json("GET", _api(repository, f"/pulls/{incident.pull_request}"), token=token)
    if not isinstance(pull, dict) or pull.get("state") != "open":
        return False, "pull request is not open"
    head = pull.get("head", {})
    if head.get("repo", {}).get("full_name") != repository:
        return False, "fork pull requests cannot receive repair credentials"
    current_sha = str(head.get("sha") or "").lower()
    if current_sha != incident.target_sha:
        return False, "incident target is stale because the pull-request branch moved"

    green, failures, pending = _check_state(repository, current_sha, token)
    if green:
        return False, "all observed checks are green"
    if pending and not failures:
        return False, "checks are still pending; callback waits for a completed failure"

    pr_comments = _paged(repository, f"/issues/{incident.pull_request}/comments", token)
    completed, latest = callback_history(pr_comments, incident)
    decision = retry_decision(
        completed_attempts=completed,
        latest_attempt_at=latest,
        now=now,
        max_attempts=max_attempts,
        cooldown_seconds=cooldown_seconds,
    )
    if not decision.allowed:
        if completed >= max_attempts:
            exhaustion = (
                f"<!-- amosclaud-repair-callback-exhausted:{incident.fingerprint}:"
                f"{incident.target_sha} -->\n"
                f"Amosclaud corrective callbacks reached the bounded limit ({completed}/"
                f"{max_attempts}) for `{incident.target_sha}`. The PR remains unmerged and the "
                "known failure remains visible. Human review or unavailable external resources "
                "are required before another attempt."
            )
            if not any("amosclaud-repair-callback-exhausted" in str(c.get("body") or "") for c in pr_comments):
                _post(repository, incident.pull_request, exhaustion, token)
        return False, decision.reason

    incident_comments = _paged(repository, f"/issues/{incident.number}/comments", token)
    run_id = _latest_repair_run(incident_comments)
    evidence = _repair_run_evidence(repository, run_id, token)
    command = build_command(incident, decision.next_attempt, failures, evidence)
    posted = _post(repository, incident.pull_request, command, token)
    _post(
        repository,
        incident.number,
        (
            f"Corrective callback attempt {decision.next_attempt}/{max_attempts} was sent to "
            f"PR #{incident.pull_request} for target `{incident.target_sha}`. "
            f"Command comment: {posted.get('html_url', 'created')}."
        ),
        token,
    )
    return True, f"callback attempt {decision.next_attempt} posted"


def issues_from_event(event_name: str, event: dict[str, Any], repository: str, token: str) -> list[dict[str, Any]]:
    if event_name == "issues":
        issue = event.get("issue")
        return [issue] if isinstance(issue, dict) else []
    if event_name in {"schedule", "workflow_dispatch"}:
        return _open_blocked_incidents(repository, token)
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-path", required=True)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--token", default=os.getenv("AMOSCLAUD_GITHUB_TOKEN", ""))
    parser.add_argument("--max-attempts", type=int, default=4)
    parser.add_argument("--cooldown-seconds", type=int, default=1_200)
    args = parser.parse_args()

    if not args.token:
        raise SystemExit("AMOSCLAUD_GITHUB_TOKEN is required for authorized callback comments")
    max_attempts = max(1, min(args.max_attempts, 8))
    cooldown = max(300, min(args.cooldown_seconds, 86_400))
    event = json.loads(open(args.event_path, encoding="utf-8").read())
    candidates = issues_from_event(args.event_name, event, args.repository, args.token)
    now = datetime.now(timezone.utc)
    sent = 0
    for issue in candidates[:50]:
        try:
            posted, reason = process_incident(
                args.repository,
                issue,
                args.token,
                max_attempts=max_attempts,
                cooldown_seconds=cooldown,
                now=now,
            )
            print(f"incident #{issue.get('number', '?')}: {reason}")
            sent += int(posted)
        except Exception as error:
            print(
                f"incident #{issue.get('number', '?')}: callback error: "
                f"{type(error).__name__}: {safe_markdown(str(error), 2_000)}",
                file=sys.stderr,
            )
    print(f"AMOSCLAUD_CALLBACK_COMMANDS_SENT={sent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
