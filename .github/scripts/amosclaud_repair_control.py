#!/usr/bin/env python3
"""Route, deduplicate, and reconcile Amosclaud repair incidents."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SUCCESS_CONCLUSIONS = {"success", "neutral", "skipped"}
FAILURE_CONCLUSIONS = {"failure", "timed_out", "action_required", "startup_failure"}
MAINTENANCE_WORKFLOWS = {
    "Amosclaud Repair Control Plane",
    "Amosclaud Autonomous Fixer",
    "Amosclaud Pull Request CI Repair",
}
REPAIR_MARKER_RE = re.compile(r"\[incident:([0-9a-f]{16,32})\]")


@dataclass
class Route:
    should_repair: bool
    route: str
    provider: str
    source: str
    target_sha: str
    target_branch: str
    base_branch: str
    source_run_id: str = ""
    status_url: str = ""
    pull_request_number: str = ""
    reason: str = ""
    fingerprint: str = ""
    incident_number: str = ""
    attempt: int = 0
    duplicate: bool = False


def _request_json(
    method: str,
    url: str,
    *,
    token: str,
    payload: dict[str, Any] | None = None,
    accept: str = "application/vnd.github+json",
) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": accept,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Amosclaud-Repair-Control/1.0",
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


def _commit_message(repository: str, sha: str, token: str) -> str:
    if not sha:
        return ""
    result = _request_json("GET", _api(repository, f"/commits/{sha}"), token=token)
    return str(result.get("commit", {}).get("message", ""))


def _repair_marker(repository: str, sha: str, token: str) -> str:
    match = REPAIR_MARKER_RE.search(_commit_message(repository, sha, token))
    return match.group(1) if match else ""


def _resolve_pr(repository: str, sha: str, token: str) -> dict[str, str]:
    if not sha:
        return {}
    pulls = _request_json(
        "GET",
        _api(repository, f"/commits/{sha}/pulls"),
        token=token,
        accept="application/vnd.github+json",
    )
    for pull in pulls or []:
        if pull.get("state") != "open":
            continue
        return {
            "number": str(pull.get("number", "")),
            "head_ref": str(pull.get("head", {}).get("ref", "")),
            "head_sha": str(pull.get("head", {}).get("sha", "")),
            "head_repo": str(pull.get("head", {}).get("repo", {}).get("full_name", "")),
            "base_ref": str(pull.get("base", {}).get("ref", "")),
        }
    return {}


def _fingerprint(repository: str, sha: str, route: str, existing: str = "") -> str:
    if existing:
        return existing
    digest = hashlib.sha256(f"{repository}|{sha}|{route}".encode("utf-8")).hexdigest()
    return digest[:20]


def _issue_title(fingerprint: str, source: str) -> str:
    compact_source = re.sub(r"\s+", " ", source).strip()[:90]
    return f"[Amosclaud Repair Incident {fingerprint}] {compact_source}"


def _search_incident(repository: str, fingerprint: str, token: str) -> dict[str, Any] | None:
    query = urllib.parse.quote(f'repo:{repository} is:issue in:title "Amosclaud Repair Incident {fingerprint}"')
    result = _request_json("GET", f"https://api.github.com/search/issues?q={query}&per_page=10", token=token)
    items = result.get("items", []) if isinstance(result, dict) else []
    return items[0] if items else None


def _body(route: Route, state: str, *, attempts: int, repair_sha: str = "") -> str:
    marker = f"<!-- amosclaud-repair-incident:{route.fingerprint} -->"
    state_marker = f"<!-- amosclaud-repair-state:{state} -->"
    repair_line = f"- Repair SHA: `{repair_sha}`\n" if repair_sha else ""
    return (
        f"{marker}\n{state_marker}\n\n"
        "## Amosclaud Repair Incident\n\n"
        f"- State: **{state}**\n"
        f"- Route: `{route.route}`\n"
        f"- Provider: `{route.provider}`\n"
        f"- Source: `{route.source}`\n"
        f"- Target revision: `{route.target_sha}`\n"
        f"- Target branch: `{route.target_branch}`\n"
        f"- Pull request: `{route.pull_request_number or 'none'}`\n"
        f"- Attempts: `{attempts}`\n"
        f"{repair_line}"
        "\nThis issue is the durable incident record. Duplicate failure events reuse it. "
        "Evidence, rejected candidates, publication status, and final CI reconciliation are attached here.\n"
    )


def _upsert_incident(repository: str, route: Route, token: str, max_attempts: int) -> Route:
    issue = _search_incident(repository, route.fingerprint, token)
    if issue:
        route.incident_number = str(issue["number"])
        existing_body = str(issue.get("body") or "")
        match = re.search(r"- Attempts: `([0-9]+)`", existing_body)
        attempts = int(match.group(1)) if match else 0
        running = "amosclaud-repair-state:running" in existing_body
        published = "amosclaud-repair-state:published" in existing_body
        same_sha = f"- Target revision: `{route.target_sha}`" in existing_body
        if running and same_sha:
            route.duplicate = True
            route.should_repair = False
            route.reason = "an identical repair incident is already running"
            route.attempt = attempts
            return route
        if attempts >= max_attempts and not published:
            route.should_repair = False
            route.reason = f"repair attempt limit reached ({attempts}/{max_attempts})"
            route.attempt = attempts
            return route
        route.attempt = attempts + 1
        _request_json(
            "PATCH",
            _api(repository, f"/issues/{route.incident_number}"),
            token=token,
            payload={"state": "open", "body": _body(route, "running", attempts=route.attempt)},
        )
        return route

    route.attempt = 1
    created = _request_json(
        "POST",
        _api(repository, "/issues"),
        token=token,
        payload={
            "title": _issue_title(route.fingerprint, route.source),
            "body": _body(route, "running", attempts=1),
        },
    )
    route.incident_number = str(created["number"])
    return route


def _all_checks_green(repository: str, sha: str, token: str) -> bool:
    checks = _request_json(
        "GET",
        _api(repository, f"/commits/{sha}/check-runs?per_page=100"),
        token=token,
        accept="application/vnd.github+json",
    )
    statuses = _request_json("GET", _api(repository, f"/commits/{sha}/status"), token=token)
    check_runs = checks.get("check_runs", []) if isinstance(checks, dict) else []
    status_items = statuses.get("statuses", []) if isinstance(statuses, dict) else []
    if not check_runs and not status_items:
        return False
    if any(item.get("status") != "completed" for item in check_runs):
        return False
    if any(item.get("conclusion") not in SUCCESS_CONCLUSIONS for item in check_runs):
        return False
    if any(item.get("state") not in {"success", "pending"} for item in status_items):
        return False
    if any(item.get("state") == "pending" for item in status_items):
        return False
    return True


def reconcile(repository: str, sha: str, token: str) -> bool:
    fingerprint = _repair_marker(repository, sha, token)
    if not fingerprint or not _all_checks_green(repository, sha, token):
        return False
    issue = _search_incident(repository, fingerprint, token)
    if not issue:
        return False
    number = int(issue["number"])
    body = str(issue.get("body") or "")
    body = re.sub(
        r"<!-- amosclaud-repair-state:[^>]+ -->",
        "<!-- amosclaud-repair-state:resolved -->",
        body,
        count=1,
    )
    body = re.sub(r"- State: \*\*[^*]+\*\*", "- State: **resolved**", body, count=1)
    if "- Repair SHA:" not in body:
        body += f"\n- Repair SHA: `{sha}`\n"
    _request_json(
        "PATCH",
        _api(repository, f"/issues/{number}"),
        token=token,
        payload={"state": "closed", "state_reason": "completed", "body": body},
    )
    _request_json(
        "POST",
        _api(repository, f"/issues/{number}/comments"),
        token=token,
        payload={"body": f"All observed checks completed successfully for repair commit `{sha}`. The incident is closed."},
    )
    return True


def classify(event_name: str, event: dict[str, Any], repository: str, default_branch: str, token: str) -> Route:
    if event_name == "workflow_run":
        run = event.get("workflow_run") or {}
        conclusion = str(run.get("conclusion") or "")
        sha = str(run.get("head_sha") or "")
        if conclusion == "success" and reconcile(repository, sha, token):
            return Route(False, "reconciled", "github_actions", str(run.get("name") or ""), sha, str(run.get("head_branch") or ""), default_branch, reason="repair checks are green and the incident was closed")
        if conclusion not in FAILURE_CONCLUSIONS:
            return Route(False, "none", "github_actions", str(run.get("name") or ""), sha, str(run.get("head_branch") or ""), default_branch, reason=f"workflow conclusion {conclusion!r} is not repairable")
        source = str(run.get("name") or "unknown workflow")
        branch = str(run.get("head_branch") or "")
        pr = _resolve_pr(repository, sha, token)
        route = "maintenance" if source in MAINTENANCE_WORKFLOWS else ("default" if branch == default_branch else "pull_request")
        if route == "pull_request" and (not pr or pr.get("head_repo") != repository):
            return Route(False, "report_only", "github_actions", source, sha, branch, default_branch, source_run_id=str(run.get("id") or ""), reason="fork or unresolved pull request cannot receive repair credentials")
        return Route(
            True,
            route,
            "github_actions",
            source,
            sha,
            pr.get("head_ref", branch) if pr else branch,
            pr.get("base_ref", default_branch) if pr else default_branch,
            source_run_id=str(run.get("id") or ""),
            status_url=str(run.get("html_url") or ""),
            pull_request_number=pr.get("number", "") if pr else "",
        )

    if event_name == "status":
        state = str(event.get("state") or "")
        context = str(event.get("context") or "")
        sha = str(event.get("sha") or "")
        if state not in {"failure", "error"} or "circleci" not in context.lower():
            return Route(False, "none", "external", context, sha, "", default_branch, reason="external status is not a failed CircleCI status")
        pr = _resolve_pr(repository, sha, token)
        route = "pull_request" if pr else "default"
        return Route(
            True,
            route,
            "circleci",
            context or "CircleCI",
            sha,
            pr.get("head_ref", default_branch),
            pr.get("base_ref", default_branch),
            status_url=str(event.get("target_url") or ""),
            pull_request_number=pr.get("number", ""),
        )

    if event_name == "schedule":
        return Route(True, "default", "scheduled_health", "scheduled repository health scan", str(event.get("after") or os.getenv("GITHUB_SHA", "")), default_branch, default_branch)

    if event_name == "workflow_dispatch":
        inputs = event.get("inputs") or {}
        scope = str(inputs.get("scope") or "default")
        pr_number = str(inputs.get("pull_request_number") or "")
        sha = str(inputs.get("target_sha") or os.getenv("GITHUB_SHA", ""))
        branch = default_branch
        base = default_branch
        if pr_number:
            pull = _request_json("GET", _api(repository, f"/pulls/{pr_number}"), token=token)
            sha = str(pull.get("head", {}).get("sha") or sha)
            branch = str(pull.get("head", {}).get("ref") or branch)
            base = str(pull.get("base", {}).get("ref") or base)
            if pull.get("head", {}).get("repo", {}).get("full_name") != repository:
                return Route(False, "report_only", "manual", "manual repair", sha, branch, base, pull_request_number=pr_number, reason="fork pull requests are report-only")
        source = str(inputs.get("source_name") or inputs.get("failure_summary") or "manual repair")
        route = "maintenance" if scope == "maintenance" else ("pull_request" if pr_number or scope == "pull_request" else "default")
        return Route(True, route, str(inputs.get("provider") or "manual"), source, sha, branch, base, source_run_id=str(inputs.get("source_run_id") or ""), status_url=str(inputs.get("status_url") or ""), pull_request_number=pr_number)

    return Route(False, "none", "unknown", event_name, "", "", default_branch, reason="unsupported event")


def _write_outputs(route: Route) -> None:
    output_path = os.getenv("GITHUB_OUTPUT")
    lines = []
    for key, value in asdict(route).items():
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = str(value)
        lines.append(f"{key}={rendered}")
    text = "\n".join(lines) + "\n"
    if output_path:
        with open(output_path, "a", encoding="utf-8") as output:
            output.write(text)
    else:
        sys.stdout.write(text)


def route_command(args: argparse.Namespace) -> int:
    event = json.loads(Path(args.event_path).read_text(encoding="utf-8"))
    route = classify(args.event_name, event, args.repository, args.default_branch, args.token)
    if route.should_repair:
        existing_marker = _repair_marker(args.repository, route.target_sha, args.token)
        route.fingerprint = _fingerprint(args.repository, route.target_sha, route.route, existing_marker)
        force_incident = os.getenv("AMOSCLAUD_FORCE_INCIDENT", "") == "1"
        if route.provider != "scheduled_health" or force_incident:
            route = _upsert_incident(args.repository, route, args.token, args.max_attempts)
    _write_outputs(route)
    return 0


def finalize_command(args: argparse.Namespace) -> int:
    issue = _request_json("GET", _api(args.repository, f"/issues/{args.incident_number}"), token=args.token)
    body = str(issue.get("body") or "")
    body = re.sub(r"<!-- amosclaud-repair-state:[^>]+ -->", f"<!-- amosclaud-repair-state:{args.state} -->", body, count=1)
    body = re.sub(r"- State: \*\*[^*]+\*\*", f"- State: **{args.state}**", body, count=1)
    if args.repair_sha and "- Repair SHA:" not in body:
        body += f"\n- Repair SHA: `{args.repair_sha}`\n"
    _request_json("PATCH", _api(args.repository, f"/issues/{args.incident_number}"), token=args.token, payload={"body": body})
    _request_json("POST", _api(args.repository, f"/issues/{args.incident_number}/comments"), token=args.token, payload={"body": args.message})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    route_parser = subparsers.add_parser("route")
    route_parser.add_argument("--event-path", required=True)
    route_parser.add_argument("--event-name", required=True)
    route_parser.add_argument("--repository", required=True)
    route_parser.add_argument("--default-branch", required=True)
    route_parser.add_argument("--token", required=True)
    route_parser.add_argument("--max-attempts", type=int, default=3)
    route_parser.set_defaults(func=route_command)

    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("--repository", required=True)
    finalize_parser.add_argument("--incident-number", required=True)
    finalize_parser.add_argument("--state", required=True)
    finalize_parser.add_argument("--message", required=True)
    finalize_parser.add_argument("--repair-sha", default="")
    finalize_parser.add_argument("--token", required=True)
    finalize_parser.set_defaults(func=finalize_command)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
