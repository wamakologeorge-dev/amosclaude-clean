#!/usr/bin/env python3
"""Submit a controlled GitHub operation to the Amosclaud task gateway."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def _boolean(name: str, default: bool = True) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise SystemExit(f"{name} must be true or false")


def _endpoint(base_url: str) -> str:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise SystemExit("AMOSCLAUD_API_URL must be an absolute HTTP(S) URL")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise SystemExit("AMOSCLAUD_API_URL must use HTTPS outside local development")
    return base_url.rstrip("/") + "/api/v1/tasks"


def _write_output(name: str, value: Any) -> None:
    output = os.getenv("GITHUB_OUTPUT", "").strip()
    if not output:
        return
    with Path(output).open("a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def main() -> int:
    api_url = _required("AMOSCLAUD_API_URL")
    api_key = _required("AMOSCLAUD_API_KEY")
    objective = _required("AMOSCLAUD_OBJECTIVE")
    repository = os.getenv("AMOSCLAUD_REPOSITORY", "").strip() or None
    payload = {
        "objective": objective,
        "repository": repository,
        "mode": os.getenv("AMOSCLAUD_MODE", "fix").strip() or "fix",
        "delivery": os.getenv("AMOSCLAUD_DELIVERY", "pull_request").strip() or "pull_request",
        "execution_target": "github" if repository else "cloud",
        "require_approval": _boolean("AMOSCLAUD_REQUIRE_APPROVAL", True),
        "metadata": {
            "source": "github-actions",
            "github_repository": os.getenv("GITHUB_REPOSITORY", ""),
            "github_run_id": os.getenv("GITHUB_RUN_ID", ""),
            "github_run_attempt": os.getenv("GITHUB_RUN_ATTEMPT", ""),
            "github_sha": os.getenv("GITHUB_SHA", ""),
            "github_ref": os.getenv("GITHUB_REF", ""),
            "github_actor": os.getenv("GITHUB_ACTOR", ""),
        },
    }
    request = urllib.request.Request(
        _endpoint(api_url),
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "amosclaud-github-sync/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        print(f"Amosclaud rejected the operation ({exc.code}): {detail}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"Could not submit the Amosclaud operation: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    Path("amosclaud-operation.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    task_id = str(result.get("id") or "")
    bucket_id = str(result.get("bucket_id") or "")
    status = str(result.get("status") or "unknown")
    if not task_id:
        print("Amosclaud returned no operation ID", file=sys.stderr)
        return 1

    _write_output("task_id", task_id)
    _write_output("bucket_id", bucket_id)
    _write_output("status", status)
    print(f"Submitted Amosclaud operation {task_id} in {status} state.")
    if bucket_id:
        print(f"Operation bucket: {bucket_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
