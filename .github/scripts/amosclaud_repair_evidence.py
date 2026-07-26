#!/usr/bin/env python3
"""Collect exact GitHub Actions or CircleCI failure evidence for Amosclaud."""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

SECRET_PATTERNS = (
    r"gh[pousr]_[A-Za-z0-9_]{20,}",
    r"amos_(?:svc|agent|auto)_[A-Za-z0-9_-]{16,}",
    r"sk-[A-Za-z0-9_-]{16,}",
    r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*[^\s]+",
)
MAX_OUTPUT = 400_000


def redact(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        if "(" in pattern and pattern.startswith("(?i)"):
            text = re.sub(pattern, lambda match: f"{match.group(1)}=[REDACTED]", text)
        else:
            text = re.sub(pattern, "[REDACTED]", text)
    if len(text) <= MAX_OUTPUT:
        return text
    half = MAX_OUTPUT // 2
    return text[:half] + "\n\n...[evidence truncated]...\n\n" + text[-half:]


def request_bytes(url: str, headers: dict[str, str]) -> bytes:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code} for {url}: {detail}") from error


def request_json(url: str, headers: dict[str, str]) -> Any:
    return json.loads(request_bytes(url, headers).decode("utf-8"))


def github_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "Amosclaud-Repair-Evidence/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def decode_log_payload(payload: bytes) -> str:
    if payload.startswith(b"PK\x03\x04"):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            chunks = []
            for name in sorted(archive.namelist()):
                chunks.append(f"\n===== {name} =====\n")
                chunks.append(archive.read(name).decode("utf-8", errors="replace"))
            return "".join(chunks)
    return payload.decode("utf-8", errors="replace")


def collect_github(repository: str, run_id: str, token: str) -> str:
    if not run_id:
        return "GitHub Actions source run ID was not provided.\n"
    headers = github_headers(token)
    base = f"https://api.github.com/repos/{repository}"
    run = request_json(f"{base}/actions/runs/{run_id}", headers)
    jobs = request_json(f"{base}/actions/runs/{run_id}/jobs?per_page=100&filter=latest", headers)
    artifacts = request_json(f"{base}/actions/runs/{run_id}/artifacts?per_page=100", headers)
    output = [
        "=== GITHUB ACTIONS RUN ===\n",
        json.dumps(
            {
                "id": run.get("id"),
                "name": run.get("name"),
                "event": run.get("event"),
                "conclusion": run.get("conclusion"),
                "head_branch": run.get("head_branch"),
                "head_sha": run.get("head_sha"),
                "html_url": run.get("html_url"),
                "run_attempt": run.get("run_attempt"),
            },
            indent=2,
        ),
        "\n\n=== FAILED JOBS AND STEPS ===\n",
    ]
    failed_jobs = [
        job
        for job in jobs.get("jobs", [])
        if job.get("conclusion") not in {"success", "neutral", "skipped"}
    ]
    for job in failed_jobs:
        output.append(
            json.dumps(
                {
                    "id": job.get("id"),
                    "name": job.get("name"),
                    "conclusion": job.get("conclusion"),
                    "started_at": job.get("started_at"),
                    "completed_at": job.get("completed_at"),
                    "runner_name": job.get("runner_name"),
                    "labels": job.get("labels"),
                    "steps": [
                        {
                            "number": step.get("number"),
                            "name": step.get("name"),
                            "status": step.get("status"),
                            "conclusion": step.get("conclusion"),
                        }
                        for step in job.get("steps", [])
                    ],
                },
                indent=2,
            )
        )
        output.append(f"\n--- LOG FOR JOB {job.get('id')} ({job.get('name')}) ---\n")
        try:
            payload = request_bytes(f"{base}/actions/jobs/{job['id']}/logs", headers)
            output.append(decode_log_payload(payload))
        except Exception as error:
            output.append(f"Unable to download job log: {type(error).__name__}: {error}\n")
    output.extend(["\n\n=== ARTIFACT METADATA ===\n", json.dumps(artifacts.get("artifacts", []), indent=2)])
    return redact("".join(output))


def _circle_headers(token: str) -> dict[str, str]:
    return {"Circle-Token": token, "Accept": "application/json", "User-Agent": "Amosclaud-Repair-Evidence/1.0"}


def _circle_build_number(status_url: str) -> str:
    matches = re.findall(r"/(\d+)(?:[/?#]|$)", status_url)
    return matches[-1] if matches else ""


def _circle_workflow_id(status_url: str) -> str:
    match = re.search(r"/workflows/([0-9a-fA-F-]{20,})", status_url)
    return match.group(1) if match else ""


def collect_circleci(repository: str, status_url: str, token: str) -> str:
    if not token:
        return "CircleCI detailed logs were requested, but CIRCLECI_TOKEN is not configured.\n"
    build_number = _circle_build_number(status_url)
    if not build_number:
        return f"Unable to resolve a CircleCI build number from status URL: {status_url}\n"
    owner, repo = repository.split("/", 1)
    headers = _circle_headers(token)
    job = request_json(
        f"https://circleci.com/api/v1.1/project/github/{owner}/{repo}/{build_number}",
        headers,
    )
    output = ["=== CIRCLECI JOB ===\n", json.dumps(job, indent=2), "\n\n=== CIRCLECI STEP OUTPUT ===\n"]
    for step in job.get("steps", []) or []:
        output.append(f"\n--- {step.get('name', 'unnamed step')} ---\n")
        for action in step.get("actions", []) or []:
            output.append(
                json.dumps(
                    {
                        "status": action.get("status"),
                        "exit_code": action.get("exit_code"),
                        "failed": action.get("failed"),
                        "run_time_millis": action.get("run_time_millis"),
                    },
                    indent=2,
                )
            )
            output_url = action.get("output_url")
            if output_url:
                try:
                    output.append("\n" + request_bytes(output_url, headers).decode("utf-8", errors="replace"))
                except Exception as error:
                    output.append(f"\nUnable to download step output: {type(error).__name__}: {error}\n")
    return redact("".join(output))


def rerun_circleci(status_url: str, token: str) -> dict[str, Any]:
    if not token:
        raise RuntimeError("CIRCLECI_TOKEN is required to rerun a failed CircleCI workflow")
    workflow_id = _circle_workflow_id(status_url)
    if not workflow_id:
        raise RuntimeError("CircleCI workflow ID could not be parsed from the status URL")
    request = urllib.request.Request(
        f"https://circleci.com/api/v2/workflow/{workflow_id}/rerun",
        data=json.dumps({"from_failed": True, "sparse_tree": False}).encode("utf-8"),
        method="POST",
        headers={
            "Circle-Token": token,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Amosclaud-Repair-Evidence/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"CircleCI rerun failed with HTTP {error.code}: {detail}") from error


def collect_command(args: argparse.Namespace) -> int:
    sections = [
        "=== AMOSCLAUD REPAIR EVIDENCE ===\n",
        json.dumps(
            {
                "provider": args.provider,
                "repository": args.repository,
                "source_run_id": args.source_run_id,
                "status_url": args.status_url,
                "source": args.source,
            },
            indent=2,
        ),
        "\n\n",
    ]
    try:
        if args.provider == "github_actions":
            sections.append(collect_github(args.repository, args.source_run_id, args.github_token))
        elif args.provider == "circleci":
            sections.append(collect_circleci(args.repository, args.status_url, args.circleci_token))
        else:
            sections.append("No provider-specific remote evidence is available. Local reproduction will be authoritative.\n")
    except Exception as error:
        sections.append(f"Evidence collector error: {type(error).__name__}: {error}\n")
    Path(args.output).write_text(redact("".join(sections)), encoding="utf-8")
    return 0


def rerun_command(args: argparse.Namespace) -> int:
    result = rerun_circleci(args.status_url, args.circleci_token)
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="command", required=True)
    collect = subs.add_parser("collect")
    collect.add_argument("--provider", required=True)
    collect.add_argument("--repository", required=True)
    collect.add_argument("--source-run-id", default="")
    collect.add_argument("--status-url", default="")
    collect.add_argument("--source", default="")
    collect.add_argument("--github-token", default=os.getenv("GITHUB_TOKEN", ""))
    collect.add_argument("--circleci-token", default=os.getenv("CIRCLECI_TOKEN", ""))
    collect.add_argument("--output", required=True)
    collect.set_defaults(func=collect_command)

    rerun = subs.add_parser("rerun-circleci")
    rerun.add_argument("--status-url", required=True)
    rerun.add_argument("--circleci-token", default=os.getenv("CIRCLECI_TOKEN", ""))
    rerun.add_argument("--output", required=True)
    rerun.set_defaults(func=rerun_command)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
