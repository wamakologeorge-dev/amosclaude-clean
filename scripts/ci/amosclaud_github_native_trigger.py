#!/usr/bin/env python3
"""Translate GitHub events into the shared Amosclaud cooperation contract.

No tracked path is excluded. Push and pull-request events send their changed-file
manifest. Scheduled and manual full-repository events send an inventory digest,
file count, and surface counts so legacy and unclassified applications remain in
scope without creating an unbounded HTTP request.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

VALID_MODES = {"inspect", "build", "fix", "deploy", "monitor"}


def _run_git(*arguments: str) -> list[str]:
    result = subprocess.run(
        ["git", *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _unique(values: Iterable[str]) -> list[str]:
    return sorted({value.strip() for value in values if value and value.strip()})


def _changed_files(payload: dict[str, Any], event: str) -> list[str]:
    files: list[str] = []
    if event == "push":
        for commit in payload.get("commits") or []:
            for key in ("added", "modified", "removed"):
                files.extend(str(path) for path in commit.get(key) or [])
        if not files:
            before = str(payload.get("before") or "")
            after = str(payload.get("after") or os.getenv("GITHUB_SHA", ""))
            if before and after and set(before) != {"0"}:
                files.extend(_run_git("diff", "--name-only", f"{before}..{after}"))
    elif event == "pull_request":
        base_ref = os.getenv("GITHUB_BASE_REF", "").strip()
        if base_ref:
            _run_git("fetch", "--no-tags", "origin", base_ref)
            files.extend(_run_git("diff", "--name-only", f"origin/{base_ref}...HEAD"))
    elif event == "issues":
        files = []
    return _unique(files)


def _all_tracked_files() -> list[str]:
    return _unique(_run_git("ls-files"))


def _surface(path: str) -> str:
    lowered = path.lower()
    root = path.split("/", 1)[0].lower()
    if root == ".github":
        return "github-native-applications"
    if root in {"legacy", "legacy-apps", "archive"} or "legacy" in lowered:
        return "legacy-applications"
    if root in {"apps", "applications"}:
        return "applications"
    if root in {"services", "service"}:
        return "services"
    if root in {"packages", "sdk", "sdks"}:
        return "packages-and-sdks"
    if root in {"amoscloud_ai", "amosclaud_bot", "amomodel", "agents"}:
        return "amosclaud-core-and-agents"
    if root in {"api-gateway", "gateway", "proxy"}:
        return "gateways-and-routing"
    if root in {"web", "pages-site", "frontend", "ui"}:
        return "web-and-control-planes"
    if root in {"infrastructure", "deploy", "deployment", "docker", "helm", "k8s"}:
        return "infrastructure-and-deployment"
    if root in {"tests", "test"} or lowered.endswith("_test.py") or "/test" in lowered:
        return "verification"
    if root in {"docs", "documentation"} or lowered.endswith(".md"):
        return "documentation-and-contracts"
    return "repository-root-or-unclassified-legacy"


def _scope(changed: list[str], all_files: list[str], event: str) -> dict[str, Any]:
    inventory = (
        all_files if event in {"schedule", "workflow_dispatch", "repository_dispatch"} else changed
    )
    manifest = "\n".join(inventory).encode()
    counts = Counter(_surface(path) for path in inventory)
    return {
        "scope": (
            "all-tracked-files"
            if event in {"schedule", "workflow_dispatch", "repository_dispatch"}
            else "all-changed-files"
        ),
        "file_count": len(inventory),
        "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
        "surface_counts": dict(sorted(counts.items())),
        "excluded_paths": [],
        "includes_legacy_applications": True,
        "includes_github_native_applications": True,
    }


def _mode(event: str) -> str | None:
    requested = os.getenv("AMOSCLAUD_REQUESTED_MODE", "").strip().lower()
    if requested in VALID_MODES:
        return requested
    if event == "schedule":
        return "monitor"
    if event == "push":
        return "build"
    if event == "pull_request":
        return "build"
    return None


def _delivery_id() -> str:
    run_id = os.getenv("GITHUB_RUN_ID", "").strip()
    if run_id:
        return f"github-run-{run_id}"
    raw = "|".join(
        [
            os.getenv("GITHUB_EVENT_NAME", ""),
            os.getenv("GITHUB_REPOSITORY", ""),
            os.getenv("GITHUB_REF", ""),
            os.getenv("GITHUB_SHA", ""),
        ]
    )
    return f"github-{hashlib.sha256(raw.encode()).hexdigest()}"


def _endpoint() -> str:
    configured = os.getenv("AMOSCLAUD_PIPELINE_URL", "").strip().rstrip("/")
    if not configured:
        return ""
    suffix = "/api/v1/pipelines/cooperation/github/events"
    if configured.endswith(suffix):
        return configured
    return f"{configured}{suffix}"


def _post(endpoint: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, separators=(",", ":")).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Amosclaud-GitHub-Native-Pipeline/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode() or "{}")


def _write_summary(output: Path, payload: dict[str, Any], result: dict[str, Any]) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY", "").strip()
    if not summary_path:
        return
    scope = payload["repository_scope"]
    pipeline = result.get("response", {}).get("pipeline", {})
    lines = [
        "## Amosclaud GitHub-native trigger",
        "",
        f"- Event: `{payload['event']}` / `{payload['action'] or 'none'}`",
        f"- Repository: `{payload['repository']}`",
        f"- Scope: `{scope['scope']}` ({scope['file_count']} files)",
        f"- Legacy applications included: `{scope['includes_legacy_applications']}`",
        f"- GitHub-native applications included: `{scope['includes_github_native_applications']}`",
        f"- Bridge status: `{result['status']}`",
    ]
    if pipeline.get("id"):
        lines.append(f"- Cooperation pipeline: `{pipeline['id']}`")
    lines.append(f"- Evidence: `{output}`")
    Path(summary_path).open("a", encoding="utf-8").write("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-path", required=True)
    parser.add_argument(
        "--output",
        default=".amosclaud/evidence/github-native-event.json",
    )
    arguments = parser.parse_args()

    event_path = Path(arguments.event_path)
    payload = json.loads(event_path.read_text(encoding="utf-8") or "{}")
    event = os.getenv("GITHUB_EVENT_NAME", "workflow_dispatch").strip() or "workflow_dispatch"
    action = str(payload.get("action") or "")
    repository = str(
        os.getenv("GITHUB_REPOSITORY")
        or (payload.get("repository") or {}).get("full_name")
        or "unknown/unknown"
    )
    changed = _changed_files(payload, event)
    all_files = _all_tracked_files()
    repository_scope = _scope(changed, all_files, event)
    requested_mode = _mode(event)
    objective = os.getenv("AMOSCLAUD_OBJECTIVE", "").strip() or None

    trigger_payload: dict[str, Any] = {
        "delivery_id": _delivery_id(),
        "event": event,
        "action": action,
        "repository": repository,
        "ref": os.getenv("GITHUB_REF", ""),
        "sha": os.getenv("GITHUB_SHA", ""),
        "actor": os.getenv("GITHUB_ACTOR", ""),
        "requested_mode": requested_mode,
        "objective": objective,
        "changed_files": changed,
        "repository_scope": repository_scope,
        "payload": {
            "run_id": os.getenv("GITHUB_RUN_ID", ""),
            "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT", ""),
            "workflow": os.getenv("GITHUB_WORKFLOW", ""),
            "head_ref": os.getenv("GITHUB_HEAD_REF", ""),
            "base_ref": os.getenv("GITHUB_BASE_REF", ""),
            "branch": os.getenv("GITHUB_REF_NAME", ""),
            "event_number": payload.get("number"),
            "issue_number": (payload.get("issue") or {}).get("number"),
            "pull_request_number": (payload.get("pull_request") or {}).get("number"),
            "surface_counts": repository_scope["surface_counts"],
        },
    }

    output = Path(arguments.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    endpoint = _endpoint()
    token = os.getenv("AMOSCLAUD_GITHUB_PIPELINE_TOKEN", "").strip()
    result: dict[str, Any] = {
        "status": "evidence_only",
        "reason": "AMOSCLAUD_PIPELINE_URL or AMOSCLAUD_GITHUB_PIPELINE_TOKEN is not configured",
    }
    exit_code = 0
    if endpoint and token:
        try:
            response = _post(endpoint, token, trigger_payload)
            result = {"status": "pipeline_created", "response": response}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            result = {
                "status": "bridge_failed",
                "http_status": exc.code,
                "reason": detail[:20_000],
            }
            exit_code = 1
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            result = {"status": "bridge_failed", "reason": str(exc)}
            exit_code = 1

    evidence = {"trigger": trigger_payload, "bridge": result}
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_summary(output, trigger_payload, result)
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
