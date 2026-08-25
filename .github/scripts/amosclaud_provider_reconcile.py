#!/usr/bin/env python3
"""Close transient provider incidents after the provider reports recovery."""

from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from amosclaud_failure_classifier import FailureClass

STATE_MARKER_RE = re.compile(r"<!-- amosclaud-repair-state:[^>]+ -->")
STATE_LINE_RE = re.compile(r"- State: \*\*[^*]+\*\*")
FIELD_RE = re.compile(r"^- (?P<name>[^:]+): `(?P<value>[^`]*)`$", re.MULTILINE)


def _request_json(
    method: str,
    url: str,
    *,
    token: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Amosclaud-Provider-Reconcile/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API {method} {url} failed: HTTP {error.code}: {detail}") from error
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def _api(repository: str, suffix: str) -> str:
    return f"https://api.github.com/repos/{repository}{suffix}"


def _fields(body: str) -> dict[str, str]:
    return {match.group("name").strip(): match.group("value").strip() for match in FIELD_RE.finditer(body)}


def _open_circleci_incidents(repository: str, token: str) -> list[dict[str, Any]]:
    query = urllib.parse.quote(
        f'repo:{repository} is:issue is:open in:title "Amosclaud Repair Incident"'
    )
    incidents: list[dict[str, Any]] = []
    for page in range(1, 6):
        result = _request_json(
            "GET",
            f"https://api.github.com/search/issues?q={query}&per_page=100&page={page}",
            token=token,
        )
        items = result.get("items", []) if isinstance(result, dict) else []
        for issue in items:
            body = str(issue.get("body") or "")
            fields = _fields(body)
            if fields.get("Provider", "").lower() == "circleci":
                incidents.append(issue)
        if len(items) < 100:
            break
    return incidents


def _latest_status_by_context(repository: str, sha: str, token: str) -> dict[str, str]:
    result = _request_json("GET", _api(repository, f"/commits/{sha}/status"), token=token)
    statuses = result.get("statuses", []) if isinstance(result, dict) else []
    latest: dict[str, str] = {}
    for status in statuses:
        context = str(status.get("context") or "")
        if context and context not in latest:
            latest[context] = str(status.get("state") or "")
    return latest


def _resolved_body(body: str, *, sha: str, context: str) -> str:
    updated = STATE_MARKER_RE.sub("<!-- amosclaud-repair-state:resolved -->", body, count=1)
    updated = STATE_LINE_RE.sub("- State: **resolved**", updated, count=1)
    classification = FailureClass.CIRCLECI_PROVIDER_FAILURE.value
    if "- Failure classification:" not in updated:
        updated += f"\n- Failure classification: `{classification}`\n"
    if "- Provider reconciliation:" not in updated:
        updated += f"- Provider reconciliation: `success`\n- Reconciled revision: `{sha}`\n- Reconciled context: `{context}`\n"
    return updated


def _close_incident(
    repository: str,
    issue: dict[str, Any],
    *,
    sha: str,
    context: str,
    token: str,
) -> bool:
    body = str(issue.get("body") or "")
    fields = _fields(body)
    if fields.get("Provider", "").lower() != "circleci":
        return False
    if fields.get("Target revision") != sha or fields.get("Source") != context:
        return False
    if "- Repair SHA:" in body:
        return False

    number = int(issue["number"])
    _request_json(
        "PATCH",
        _api(repository, f"/issues/{number}"),
        token=token,
        payload={
            "state": "closed",
            "state_reason": "completed",
            "body": _resolved_body(body, sha=sha, context=context),
        },
    )
    _request_json(
        "POST",
        _api(repository, f"/issues/{number}/comments"),
        token=token,
        payload={
            "body": (
                f"CircleCI recovered for `{context}` on `{sha}`. The same revision is now "
                "successful, so no source repair is required. Amosclaud classified this as "
                f"`{FailureClass.CIRCLECI_PROVIDER_FAILURE.value}` and closed the incident."
            )
        },
    )
    return True


def reconcile_status_event(event: dict[str, Any], repository: str, token: str) -> int:
    state = str(event.get("state") or "").lower()
    context = str(event.get("context") or "")
    sha = str(event.get("sha") or "")
    if state != "success" or "circleci" not in context.lower() or not sha:
        return 0

    closed = 0
    for issue in _open_circleci_incidents(repository, token):
        if _close_incident(repository, issue, sha=sha, context=context, token=token):
            closed += 1
    return closed


def reconcile_sweep(repository: str, token: str) -> int:
    closed = 0
    status_cache: dict[str, dict[str, str]] = {}
    for issue in _open_circleci_incidents(repository, token):
        body = str(issue.get("body") or "")
        fields = _fields(body)
        sha = fields.get("Target revision", "")
        context = fields.get("Source", "")
        if not sha or not context or "- Repair SHA:" in body:
            continue
        if sha not in status_cache:
            status_cache[sha] = _latest_status_by_context(repository, sha, token)
        if status_cache[sha].get(context) != "success":
            continue
        if _close_incident(repository, issue, sha=sha, context=context, token=token):
            closed += 1
    return closed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--event-path", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--token", required=True)
    args = parser.parse_args()

    if args.event_name == "status":
        event = json.loads(Path(args.event_path).read_text(encoding="utf-8"))
        closed = reconcile_status_event(event, args.repository, args.token)
    else:
        closed = reconcile_sweep(args.repository, args.token)
    print(json.dumps({"closed_incidents": closed, "event_name": args.event_name}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
