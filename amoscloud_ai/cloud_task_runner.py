"""Cloud and connected-GitHub execution for Global Task Router jobs."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

import httpx
from git import Repo
from git.exc import GitCommandError

from amoscloud_ai import provider
from amoscloud_ai.agent_tokens import credit_tokens
from amoscloud_ai.api.routes.auth import _connect
from amoscloud_ai.api.routes.github_repositories import (
    _authenticated_clone_url,
    _connection,
    _db as github_db,
    _decrypt_token,
    _public_remote_url,
)
from amoscloud_ai.api.routes.task_router import _ensure_schema, _event, _json, _now
from amoscloud_ai.engineering_agent import EngineeringAgentError, run_engineering_agent


def _finish(
    task_id: str,
    status: str,
    summary: str,
    *,
    artifacts=None,
    pull_request_url=None,
    evidence=None,
) -> None:
    with _connect() as db:
        _ensure_schema(db)
        task = db.execute(
            "SELECT * FROM global_tasks WHERE id=?", (task_id,)
        ).fetchone()
        if not task or task["status"] not in {"queued", "running"}:
            return
        db.execute(
            """UPDATE global_tasks
               SET status=?,summary=?,artifacts_json=?,pull_request_url=?,finished_at=?
               WHERE id=?""",
            (
                status,
                summary[:20_000],
                _json(artifacts or []),
                pull_request_url,
                _now(),
                task_id,
            ),
        )
        if status == "failed":
            credit_tokens(
                db,
                int(task["user_id"]),
                int(task["reserved_credits"]),
                reason="task_failure_refund",
                reference=task_id,
            )
        _event(
            db,
            task_id,
            f"task.{status}",
            summary[:20_000],
            {"evidence": (evidence or [])[:200], "artifacts": (artifacts or [])[:100]},
        )
        db.commit()
    from amoscloud_ai.api.routes.webhooks import dispatch_webhook_event

    dispatch_webhook_event(
        int(task["user_id"]),
        f"task.{status}",
        {
            "task_id": task_id,
            "status": status,
            "summary": summary[:20_000],
            "artifacts": artifacts or [],
            "pull_request_url": pull_request_url,
        },
    )


def _start(task_id: str) -> dict | None:
    with _connect() as db:
        _ensure_schema(db)
        db.execute("BEGIN IMMEDIATE")
        task = db.execute(
            "SELECT * FROM global_tasks WHERE id=?", (task_id,)
        ).fetchone()
        if not task or task["status"] != "queued":
            db.rollback()
            return None
        cursor = db.execute(
            "UPDATE global_tasks SET status='running',started_at=? WHERE id=? AND status='queued'",
            (_now(), task_id),
        )
        if cursor.rowcount != 1:
            db.rollback()
            return None
        _event(
            db,
            task_id,
            "task.started",
            f"Started on {task['execution_target']} execution target.",
        )
        db.commit()
        return dict(task)


def _repository(task: dict) -> dict:
    repository = (task.get("repository") or "").strip()
    if not repository:
        raise RuntimeError(
            "A connected repository is required for this execution target"
        )
    with github_db() as db:
        row = db.execute(
            """SELECT * FROM repositories
               WHERE owner_id=? AND (github_full_name=? OR name=?)
               ORDER BY github_full_name IS NOT NULL DESC LIMIT 1""",
            (task["user_id"], repository, repository),
        ).fetchone()
        if not row or not row["github_full_name"]:
            raise RuntimeError(
                "Connect and import this GitHub repository before routing work"
            )
        connection = _connection(db, int(task["user_id"]))
        token = _decrypt_token(connection["access_token_ciphertext"])
    return {**dict(row), "token": token}


def _ask_only(task: dict) -> tuple[str, list[str]]:
    result = provider.reply(
        [{"role": "user", "content": task["objective"]}],
        "You are Amosclaud. Return a concise, evidence-aware engineering response. Do not claim files changed.",
    )
    if result.status != "ready":
        raise RuntimeError("Amosclaud provider runtime is not ready")
    return result.reply, [f"Provider runtime: {result.runtime}"]


def _run_tests(root: Path) -> list[str]:
    if not (root / "tests").is_dir():
        return ["No tests directory was found."]
    completed = subprocess.run(
        [os.sys.executable, "-m", "pytest", "-q"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    output = (completed.stdout + "\n" + completed.stderr)[-12_000:]
    if completed.returncode:
        raise RuntimeError("Repository tests failed:\n" + output)
    return [output]


def _github_work(task: dict) -> tuple[str, list[dict], str | None, list[str]]:
    repository = _repository(task)
    tempdir = Path(tempfile.mkdtemp(prefix=f"amosclaud-{task['id']}-"))
    token = repository.pop("token")
    branch = f"amosclaud/task-{task['id'].removeprefix('task_')[:12]}"
    base = (
        repository.get("github_default_branch")
        or repository.get("default_branch")
        or "main"
    )
    evidence: list[str] = []
    artifacts: list[dict] = []
    pull_request_url: str | None = None
    try:
        Repo.clone_from(
            _authenticated_clone_url(repository["github_full_name"], token),
            tempdir,
            branch=base,
            depth=1,
        )
        repo = Repo(tempdir)
        repo.remote("origin").set_url(
            _public_remote_url(repository["github_full_name"])
        )
        repo.git.checkout("-b", branch)

        if task["mode"] in {"ask", "review", "monitor"}:
            run = run_engineering_agent(tempdir, task["objective"], apply_changes=False)
        elif task["mode"] == "test":
            test_output = _run_tests(tempdir)
            return "Repository tests completed successfully.", [], None, test_output
        else:
            run = run_engineering_agent(tempdir, task["objective"], apply_changes=True)

        evidence.extend(run.evidence)
        evidence.extend(
            f"{check['name']}: {'passed' if check.get('passed') else 'failed'}"
            for check in run.checks
        )
        if any(not check.get("passed", False) for check in run.checks):
            raise RuntimeError(
                "Verification failed after applying the proposed changes"
            )

        diff = repo.git.diff("--", ".")
        if diff:
            artifacts.append(
                {
                    "type": "patch",
                    "name": f"{task['id']}.patch",
                    "content": diff[:200_000],
                }
            )

        if task["delivery"] == "pull_request" and repo.is_dirty(untracked_files=True):
            repo.git.add(A=True)
            with repo.config_writer() as config:
                config.set_value("user", "name", "Amosclaud Task Router")
                config.set_value("user", "email", "agent@amosclaud.com")
            repo.index.commit(f"Amosclaud: {task['objective'][:72]}")
            remote = repo.remote("origin")
            remote.set_url(
                _authenticated_clone_url(repository["github_full_name"], token)
            )
            try:
                repo.git.push("--set-upstream", "origin", branch)
            finally:
                remote.set_url(_public_remote_url(repository["github_full_name"]))
            response = httpx.post(
                f"https://api.github.com/repos/{repository['github_full_name']}/pulls",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json={
                    "title": f"Amosclaud: {task['objective'][:80]}",
                    "head": branch,
                    "base": base,
                    "body": (
                        "Requested through the Amosclaud Global Task Router.\n\n"
                        f"Task: {task['id']}\n\n"
                        "Verification evidence is available in the Amosclaud task log."
                    ),
                },
                timeout=30,
            )
            response.raise_for_status()
            pull_request_url = response.json()["html_url"]
            artifacts.append({"type": "pull_request", "url": pull_request_url})

        return run.summary, artifacts, pull_request_url, evidence
    except (GitCommandError, httpx.HTTPError, EngineeringAgentError) as exc:
        raise RuntimeError(
            f"Connected GitHub execution failed safely: {type(exc).__name__}"
        ) from exc
    finally:
        shutil.rmtree(tempdir, ignore_errors=True)


def execute_cloud_task(task_id: str) -> None:
    task = _start(task_id)
    if not task:
        return
    try:
        if task["execution_target"] == "cloud" and not task.get("repository"):
            summary, evidence = _ask_only(task)
            _finish(task_id, "completed", summary, evidence=evidence)
            return
        summary, artifacts, pull_request_url, evidence = _github_work(task)
        _finish(
            task_id,
            "completed",
            summary,
            artifacts=artifacts,
            pull_request_url=pull_request_url,
            evidence=evidence,
        )
    except Exception as exc:
        _finish(
            task_id,
            "failed",
            f"Execution stopped safely: {type(exc).__name__}",
            evidence=["Reserved credits were refunded."],
        )


def dispatch_cloud_task(task_id: str) -> None:
    """Dispatch durably when Celery is reachable, otherwise use a bounded local thread."""
    try:
        from amoscloud_ai.task_dispatch import dispatch_task
        from amoscloud_ai.worker import run_global_task

        dispatch_task(run_global_task, task_id)
    except Exception:
        thread = threading.Thread(
            target=execute_cloud_task,
            args=(task_id,),
            name=f"amosclaud-task-{task_id[-8:]}",
            daemon=True,
        )
        thread.start()
