"""Outbound-only client for an Amosclaud self-hosted task runner."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import time
from pathlib import Path

import httpx

from amoscloud_ai.engineering_agent import EngineeringAgentError, run_engineering_agent


class RunnerConfigurationError(RuntimeError):
    pass


def _configuration() -> tuple[str, str, str, Path, float]:
    api_url = os.getenv("AMOSCLAUD_API_URL", "https://amosclaud.com").strip().rstrip("/")
    runner_id = os.getenv("AMOSCLAUD_RUNNER_ID", "").strip()
    runner_token = os.getenv("AMOSCLAUD_RUNNER_TOKEN", "").strip()
    workspace_raw = os.getenv("AMOSCLAUD_RUNNER_WORKSPACE", "").strip()
    if not runner_id or not runner_token or not workspace_raw:
        raise RunnerConfigurationError(
            "AMOSCLAUD_RUNNER_ID, AMOSCLAUD_RUNNER_TOKEN, and AMOSCLAUD_RUNNER_WORKSPACE are required"
        )
    workspace = Path(workspace_raw).expanduser().resolve()
    if not workspace.is_dir():
        raise RunnerConfigurationError("AMOSCLAUD_RUNNER_WORKSPACE must be an existing folder")
    interval = max(5.0, min(float(os.getenv("AMOSCLAUD_RUNNER_POLL_SECONDS", "15")), 300.0))
    return api_url, runner_id, runner_token, workspace, interval


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _heartbeat(client: httpx.Client, api_url: str, runner_id: str, token: str) -> None:
    model_url = os.getenv("AMOSCLAUD_MODEL_URL", "").strip().rstrip("/")
    model_status = {"ready": False}
    capabilities = ["ask", "build", "test", "review", "monitor"]
    if model_url:
        try:
            health = client.get(f"{model_url}/health", headers=_model_headers(), timeout=10)
            health.raise_for_status()
            health_payload = health.json()
            model_status = {
                "ready": health_payload.get("status") == "ready",
                "name": health_payload.get("model", "amosclaud-folder-v1"),
                "checkpoint": bool(health_payload.get("checkpoint")),
            }
            if model_status["ready"]:
                capabilities.append("model.inference")
        except httpx.HTTPError:
            model_status = {"ready": False, "detail": "local model is unreachable"}
    response = client.post(
        f"{api_url}/api/v1/runners/{runner_id}/heartbeat",
        headers=_headers(token),
        json={
            "version": "1.0.1",
            "capabilities": capabilities,
            "system": {
                "platform": platform.system(),
                "python": platform.python_version(),
                "machine": platform.machine(),
                "model": model_status,
            },
        },
    )
    response.raise_for_status()


def _model_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = os.getenv("AMOSCLAUD_MODEL_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _serve_model_request(client: httpx.Client, api_url: str, runner_id: str, token: str) -> bool:
    response = client.post(
        f"{api_url}/api/v1/model-network/stations/{runner_id}/claim",
        headers=_headers(token),
    )
    response.raise_for_status()
    request = response.json()
    if request is None:
        return False
    model_url = os.getenv("AMOSCLAUD_MODEL_URL", "").strip().rstrip("/")
    result: dict[str, str | None]
    try:
        completion = client.post(
            f"{model_url}/v1/chat/completions",
            headers=_model_headers(),
            json={
                "model": request["model"],
                "messages": request["messages"],
                "temperature": request.get("temperature", 0.2),
                "max_tokens": request.get("max_tokens", 1200),
            },
            timeout=float(os.getenv("AMOSCLAUD_MODEL_TIMEOUT", "120")),
        )
        completion.raise_for_status()
        reply = completion.json()["choices"][0]["message"]["content"]
        result = {"status": "completed", "reply": reply, "runtime": "folder-native"}
    except (httpx.HTTPError, KeyError, TypeError) as error:
        result = {
            "status": "failed",
            "reply": None,
            "runtime": "folder-native",
            "error": type(error).__name__,
        }
    completed = client.post(
        f"{api_url}/api/v1/model-network/stations/{runner_id}/requests/{request['id']}/complete",
        headers=_headers(token),
        json=result,
    )
    completed.raise_for_status()
    return True


def _test_workspace(workspace: Path) -> tuple[str, list[str]]:
    if not (workspace / "tests").is_dir():
        return "No tests directory was found.", ["No test command was executed."]
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    output = (result.stdout + "\n" + result.stderr)[-12_000:]
    if result.returncode:
        raise RuntimeError("Workspace tests failed")
    return "Workspace tests completed successfully.", [output]


def _execute(task: dict, workspace: Path) -> dict:
    mode = task["mode"]
    if mode == "test":
        summary, evidence = _test_workspace(workspace)
        return {"status": "completed", "summary": summary, "evidence": evidence}

    apply_changes = mode in {"build", "deploy"}
    run = run_engineering_agent(
        workspace,
        task["objective"],
        apply_changes=apply_changes,
    )
    failed = [check for check in run.checks if not check.get("passed", False)]
    if failed:
        return {
            "status": "failed",
            "summary": "The self-hosted runner stopped because verification failed.",
            "evidence": [
                *run.evidence,
                *[f"{check['name']}: failed" for check in failed],
            ],
        }

    artifacts: list[dict] = []
    git_dir = workspace / ".git"
    if git_dir.exists():
        diff = subprocess.run(
            ["git", "diff", "--", "."],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        ).stdout
        if diff:
            artifacts.append(
                {
                    "type": "patch",
                    "name": f"{task['id']}.patch",
                    "content": diff[:200_000],
                }
            )
    return {
        "status": "completed",
        "summary": run.summary,
        "evidence": run.evidence,
        "artifacts": artifacts,
    }


def run_once(
    client: httpx.Client,
    api_url: str,
    runner_id: str,
    token: str,
    workspace: Path,
) -> bool:
    _heartbeat(client, api_url, runner_id, token)
    if _serve_model_request(client, api_url, runner_id, token):
        return True
    response = client.post(
        f"{api_url}/api/v1/runners/{runner_id}/claim",
        headers=_headers(token),
    )
    response.raise_for_status()
    task = response.json()
    if task is None:
        return False

    try:
        result = _execute(task, workspace)
    except (EngineeringAgentError, RuntimeError, subprocess.SubprocessError) as exc:
        result = {
            "status": "failed",
            "summary": f"Self-hosted execution stopped safely: {type(exc).__name__}",
            "evidence": [],
        }

    completed = client.post(
        f"{api_url}/api/v1/runners/{runner_id}/tasks/{task['id']}/complete",
        headers=_headers(token),
        json=result,
    )
    completed.raise_for_status()
    return True


def main() -> None:
    api_url, runner_id, token, workspace, interval = _configuration()
    print(f"Amosclaud runner {runner_id} watching {workspace}")
    with httpx.Client(timeout=180) as client:
        while True:
            try:
                worked = run_once(client, api_url, runner_id, token, workspace)
                if worked:
                    continue
            except httpx.HTTPStatusError as exc:
                print(
                    f"Runner API rejected the request: {exc.response.status_code}",
                    file=sys.stderr,
                )
            except httpx.HTTPError as exc:
                print(f"Runner network error: {type(exc).__name__}", file=sys.stderr)
            time.sleep(interval)


if __name__ == "__main__":
    main()
