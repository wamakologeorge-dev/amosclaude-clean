#!/usr/bin/env python3
"""Consolidate recurrent Amosclaud repair failures into durable incidents."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from typing import Any, Iterable

BOT_LOGINS = {
    "github-actions[bot]",
    "amosclaud-fixer[bot]",
    "amosclaud-bot[bot]",
}

LEGACY_PREFIXES = (
    "Amosclaud Fixer could not repair ",
    "Amosclaud background engineer needs owner review",
    "Amosclaud autonomous repair ",
)

FIELD_RE = re.compile(r"^- (?P<label>[^:]+): `(?P<value>[^`]+)`\s*$", re.MULTILINE)
COMMIT_RE = re.compile(r"(?:commit|revision)\s+`?([0-9a-f]{7,40})`?", re.IGNORECASE)
RUN_URL_RE = re.compile(r"https://github\.com/[^\s)]+/actions/runs/[0-9]+")


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
            "User-Agent": "Amosclaud-Incident-Deduplicator/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GitHub API {method} {url} failed: HTTP {error.code}: {detail}"
        ) from error
    return json.loads(body.decode("utf-8")) if body else None


def _api(repository: str, suffix: str) -> str:
    return f"https://api.github.com/repos/{repository}{suffix}"


def _normalize(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip().lower()
    return re.sub(r"[^a-z0-9._:/ -]+", "", value)


def _fields(body: str) -> dict[str, str]:
    return {
        match.group("label").strip().lower(): match.group("value").strip()
        for match in FIELD_RE.finditer(body)
    }


def _legacy_identity(title: str) -> tuple[str, str] | None:
    prefix = LEGACY_PREFIXES[0]
    if title.startswith(prefix):
        raw = title[len(prefix) :].strip()
        provider, separator, source = raw.partition(":")
        if separator:
            return provider, source
        return "legacy", raw
    if title.startswith(LEGACY_PREFIXES[1]):
        return "github_actions", "background engineer"
    if title.startswith(LEGACY_PREFIXES[2]):
        return "github_actions", "autonomous repair"
    return None


def canonical_key(issue: dict[str, Any]) -> str | None:
    """Return a stable incident key that intentionally excludes commit SHA."""
    if issue.get("pull_request"):
        return None
    login = str((issue.get("user") or {}).get("login") or "")
    if login not in BOT_LOGINS:
        return None

    title = str(issue.get("title") or "")
    body = str(issue.get("body") or "")
    fields = _fields(body)

    provider = fields.get("provider", "")
    source = fields.get("source", "")
    route = fields.get("route", "default")
    branch = fields.get("target branch", "")
    pull_request = fields.get("pull request", "")

    if not provider or not source:
        legacy = _legacy_identity(title)
        if not legacy:
            return None
        provider, source = legacy
        route = "default"

    if pull_request and pull_request.lower() not in {"none", "unknown", ""}:
        scope = f"pr:{pull_request}"
    else:
        scope = f"branch:{branch or 'default'}"

    return "|".join(
        (
            _normalize(route or "default"),
            _normalize(provider),
            _normalize(source),
            _normalize(scope),
        )
    )


def marker_for_key(key: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
    return f"<!-- amosclaud-canonical-incident:{digest} -->"


def _issue_summary(issue: dict[str, Any]) -> str:
    body = str(issue.get("body") or "")
    commit = COMMIT_RE.search(body)
    run_url = RUN_URL_RE.search(body)
    details = [f"- Duplicate record: #{issue['number']}"]
    if commit:
        details.append(f"- Reported revision: `{commit.group(1)}`")
    if run_url:
        details.append(f"- Evidence: {run_url.group(0)}")
    details.append(
        "- Action: evidence was preserved here and the duplicate record was closed"
    )
    return "\n".join(details)


def _list_issues(repository: str, token: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    page = 1
    while True:
        items = _request_json(
            "GET",
            _api(
                repository,
                f"/issues?state=all&per_page=100&page={page}&sort=created&direction=asc",
            ),
            token=token,
        )
        if not isinstance(items, list) or not items:
            break
        issues.extend(item for item in items if not item.get("pull_request"))
        if len(items) < 100:
            break
        page += 1
    return issues


def _patch_issue(
    repository: str,
    number: int,
    token: str,
    payload: dict[str, Any],
) -> None:
    _request_json(
        "PATCH",
        _api(repository, f"/issues/{number}"),
        token=token,
        payload=payload,
    )


def _comment(repository: str, number: int, token: str, body: str) -> None:
    _request_json(
        "POST",
        _api(repository, f"/issues/{number}/comments"),
        token=token,
        payload={"body": body},
    )


def _created_at(issue: dict[str, Any]) -> str:
    return str(issue.get("created_at") or "")


def _choose_canonical(group: list[dict[str, Any]], marker: str) -> dict[str, Any]:
    marked = [item for item in group if marker in str(item.get("body") or "")]
    if marked:
        open_marked = [item for item in marked if item.get("state") == "open"]
        return min(open_marked or marked, key=_created_at)

    open_items = [item for item in group if item.get("state") == "open"]
    if open_items:
        return min(open_items, key=_created_at)
    return max(group, key=_created_at)


def _ensure_canonical(
    repository: str,
    canonical: dict[str, Any],
    marker: str,
    token: str,
) -> None:
    body = str(canonical.get("body") or "")
    payload: dict[str, Any] = {}
    if marker not in body:
        payload["body"] = f"{marker}\n{body}".rstrip() + "\n"
    if canonical.get("state") != "open":
        payload["state"] = "open"
    if payload:
        _patch_issue(repository, int(canonical["number"]), token, payload)


def _close_duplicate(
    repository: str,
    canonical: dict[str, Any],
    duplicate: dict[str, Any],
    token: str,
) -> None:
    canonical_number = int(canonical["number"])
    duplicate_number = int(duplicate["number"])
    _comment(
        repository,
        canonical_number,
        token,
        "### Recurrent repair failure consolidated\n\n"
        + _issue_summary(duplicate),
    )
    _comment(
        repository,
        duplicate_number,
        token,
        f"This recurrent repair event is tracked in canonical incident #{canonical_number}. "
        "The evidence was copied there, so this duplicate is being closed.",
    )
    _patch_issue(
        repository,
        duplicate_number,
        token,
        {"state": "closed", "state_reason": "duplicate"},
    )


def deduplicate(
    repository: str,
    token: str,
    *,
    issue_number: int | None = None,
) -> dict[str, int]:
    issues = _list_issues(repository, token)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for issue in issues:
        key = canonical_key(issue)
        if key:
            groups[key].append(issue)

    if issue_number is not None:
        groups = {
            key: group
            for key, group in groups.items()
            if any(int(item["number"]) == issue_number for item in group)
        }

    canonical_count = 0
    closed_count = 0
    for key, group in groups.items():
        marker = marker_for_key(key)
        canonical = _choose_canonical(group, marker)
        _ensure_canonical(repository, canonical, marker, token)
        canonical_count += 1
        for duplicate in group:
            if int(duplicate["number"]) == int(canonical["number"]):
                continue
            if duplicate.get("state") != "open":
                continue
            _close_duplicate(repository, canonical, duplicate, token)
            closed_count += 1

    return {"canonical": canonical_count, "duplicates_closed": closed_count}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--issue-number", type=int)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = deduplicate(
        args.repository,
        args.token,
        issue_number=args.issue_number,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
