"""Cloud and connected-GitHub execution for Global Task Router jobs.

Every repository-derived compiler, test, typecheck, and build command is routed
through the locked-down Amosclaud runner container. Production dispatch is
fail-closed: if the durable worker queue is unavailable, the task remains queued
for recovery instead of being executed in a process-local daemon thread.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
from datetime import datetime, timezone
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
from amosclaud_bot.bot import AmosclaudBot
from src.services.runtime_exec import RuntimeExecutor


def _production() -> bool:
    value = os.getenv("AMOSCLAUD_ENV") or os.getenv("ENVIRONMENT") or "development"
    return value.strip().lower() in {"production", "prod"}


def _finish(
    task_id: str,
    status: str,
    summary: str,
    *,
    artifacts=None,
    pull_request_url=None,
    evidence=None,
    verification_id: str | None = None,
) -> None:
    if status == "completed" and (not verification_id or not evidence):
        status = "failed"
        summary = "Completion blocked: a verification_id and real evidence are required."
    with _connect() as db:
        _ensure_schema(db)
        task = db.execute(
            "SELECT * FROM global_tasks WHERE id=?", (task_id,)
        ).fetchone()
        if not task or task["status"] not in {"queued", "running"}:
            return
        db.execute(
            """UPDATE global_tasks
               SET status=?,summary=?,artifacts_json=?,pull_request_url=?,
                   verification_id=?,finished_at=?
               WHERE id=?""",
            (
                status,
                summary[:20_000],
                _json(artifacts or []),
                pull_request_url,
                verification_id,
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
            {
                "evidence": (evidence or [])[:200],
                "artifacts": (artifacts or [])[:100],
                "verification_id": verification_id,
            },
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
            "verification_id": verification_id,
            "bucket_id": task["bucket_id"],
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
        raise RuntimeError("A connected repository is required for this execution target")
    with github_db() as db:
        row = db.execute(
            """SELECT * FROM repositories
               WHERE owner_id=? AND (github_full_name=? OR name=?)
               ORDER BY github_full_name IS NOT NULL DESC LIMIT 1""",
            (task["user_id"], repository, repository),
        ).fetchone()
        if not row or not row["github_full_name"]:
            raise RuntimeError("Connect and import this GitHub repository before routing work")
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


def _changed_paths(repo: Repo) -> list[str]:
    """Return every tracked or untracked path changed from the cloned base."""
    tracked = [
        line.strip()
        for line in repo.git.diff("HEAD", "--name-only").splitlines()
        if line.strip()
    ]
    return list(dict.fromkeys([*tracked, *repo.untracked_files]))


def _verification_evidence(checks: list[dict[str, object]]) -> list[str]:
    evidence: list[str] = []
    for check in checks:
        name = str(check.get("name") or "verification")
        state = "passed" if check.get("passed") else "failed"
        command = str(check.get("command") or "")
        summary = str(check.get("summary") or "No output")
        evidence.append(f"{name}: {state}; command={command}; {summary}"[:2000])
    return evidence


def _run_verification(
    root: Path,
    changed_files: list[str] | None = None,
) -> tuple[list[str], list[dict[str, object]]]:
    """Run deterministic checks only inside the configured isolated runner."""
    checks = RuntimeExecutor(root).verify(changed_files=changed_files or [])
    if not checks:
        raise RuntimeError(
            "No deterministic repository verification command could be selected"
        )
    evidence = _verification_evidence(checks)
    failed = [check for check in checks if not check.get("passed")]
    if failed:
        details = "\n\n".join(
            str(check.get("output") or check.get("summary") or "verification failed")
            for check in failed[:8]
        )
        raise RuntimeError("Isolated repository verification failed:\n" + details[-12_000:])
    return evidence, checks


def _run_tests(root: Path) -> list[str]:
    """Compatibility wrapper retained for callers that request repository tests."""
    evidence, _checks = _run_verification(root, [])
    return evidence


def _verification_id(task_id: str, commit_sha: str, evidence: list[str]) -> str:
    payload = json.dumps(
        {"task_id": task_id, "commit_sha": commit_sha, "evidence": evidence},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "verify_" + hashlib.sha256(payload).hexdigest()[:32]


def _assert_base_unchanged(
    repo: Repo,
    *,
    repository_full_name: str,
    token: str,
    base: str,
    expected_sha: str,
) -> None:
    """Refuse publication when the target branch moved during the operation."""
    remote = repo.remote("origin")
    remote.set_url(_authenticated_clone_url(repository_full_name, token))
    try:
        repo.git.fetch("origin", base, depth=1)
        current_sha = repo.commit(f"origin/{base}").hexsha
    finally:
        remote.set_url(_public_remote_url(repository_full_name))
    if current_sha != expected_sha:
        raise RuntimeError(
            "The target branch moved while Amosclaud was working; the task must be "
            "replanned against the new revision before publication"
        )


def _github_work(
    task: dict,
) -> tuple[str, list[dict], str | None, list[str], str]:
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
        base_sha = repo.head.commit.hexsha
        repo.remote("origin").set_url(_public_remote_url(repository["github_full_name"]))
        repo.git.checkout("-b", branch)

        if task["mode"] == "test":
            test_evidence, checks = _run_verification(tempdir, [])
            evidence.extend(test_evidence)
            commit_sha = repo.head.commit.hexsha
            verification_id = _verification_id(task["id"], commit_sha, evidence)
            has_tests = any("test" in str(check.get("name") or "").lower() for check in checks)
            summary = (
                "Repository tests completed successfully."
                if has_tests
                else "Repository verification completed; no automated test suite was detected."
            )
            return summary, [], None, evidence, verification_id

        if task["mode"] in {"fix", "review", "monitor"}:
            command = {
                "fix": "fix",
                "review": "review",
                "monitor": "inspect",
            }[task["mode"]]
            result = AmosclaudBot(
                repository["github_full_name"],
                token,
                tempdir,
            ).execute_operation(
                command,
                task["objective"],
                allow_writes=task["mode"] == "fix",
            )
            if str(result.get("status") or "").lower() in {
                "failed",
                "blocked",
                "error",
            }:
                raise RuntimeError("Amosclaud Bot stopped the operation safely")
            summary = str(
                result.get("summary")
                or result.get("message")
                or f"Amosclaud Bot completed {command}."
            )
            evidence.extend(str(item) for item in result.get("evidence") or [])
            checks = list(result.get("checks") or [])
            evidence.extend(
                f"{check.get('name', 'check')}: "
                f"{'passed' if check.get('passed') is not False else 'failed'}"
                for check in checks
            )
            if any(
                str(check.get("status") or "").lower()
                in {"failed", "failure", "error"}
                or check.get("passed") is False
                for check in checks
            ):
                raise RuntimeError("Doctor verification failed after the Bot operation")
        else:
            run = run_engineering_agent(
                tempdir,
                task["objective"],
                apply_changes=task["mode"] in {"build", "deploy"},
            )
            summary = run.summary
            evidence.extend(run.evidence)
            evidence.extend(
                f"{check['name']}: {'passed' if check.get('passed') else 'failed'}"
                for check in run.checks
            )
            if any(not check.get("passed", False) for check in run.checks):
                raise RuntimeError("Verification failed after applying the proposed changes")

        changed_files = _changed_paths(repo)
        if task["mode"] in {"build", "deploy", "fix"} and changed_files:
            verification_evidence, _checks = _run_verification(
                tempdir,
                changed_files,
            )
            evidence.extend(verification_evidence)

        diff = repo.git.diff("HEAD", "--", ".")
        if diff:
            artifacts.append(
                {
                    "type": "patch",
                    "name": f"{task['id']}.patch",
                    "content": diff[:200_000],
                }
            )

        if task["delivery"] == "pull_request" and changed_files:
            repo.git.add(A=True)
            with repo.config_writer() as config:
                config.set_value("user", "name", "Amosclaud Task Router")
                config.set_value("user", "email", "agent@amosclaud.com")
            repo.index.commit(f"Amosclaud: {task['objective'][:72]}")
            _assert_base_unchanged(
                repo,
                repository_full_name=repository["github_full_name"],
                token=token,
                base=base,
                expected_sha=base_sha,
            )
            remote = repo.remote("origin")
            remote.set_url(_authenticated_clone_url(repository["github_full_name"], token))
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
                    "draft": True,
                    "body": (
                        "Requested through the Amosclaud Global Task Router.\n\n"
                        f"Bucket: {task['bucket_id']}\n"
                        f"Task: {task['id']}\n\n"
                        "Verification evidence is available in the Amosclaud task log."
                    ),
                },
                timeout=30,
            )
            response.raise_for_status()
            pull_request_url = response.json()["html_url"]
            artifacts.append({"type": "pull_request", "url": pull_request_url})

        commit_sha = repo.head.commit.hexsha
        verification_id = _verification_id(task["id"], commit_sha, evidence)
        artifacts.append(
            {
                "type": "verification",
                "verification_id": verification_id,
                "commit_sha": commit_sha,
            }
        )
        return summary, artifacts, pull_request_url, evidence, verification_id
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
            verification_id = _verification_id(task_id, "conversation", evidence)
            _finish(
                task_id,
                "completed",
                summary,
                evidence=evidence,
                verification_id=verification_id,
            )
            return
        (
            summary,
            artifacts,
            pull_request_url,
            evidence,
            verification_id,
        ) = _github_work(task)
        _finish(
            task_id,
            "completed",
            summary,
            artifacts=artifacts,
            pull_request_url=pull_request_url,
            evidence=evidence,
            verification_id=verification_id,
        )
    except Exception as exc:
        _finish(
            task_id,
            "failed",
            f"Execution stopped safely: {type(exc).__name__}",
            evidence=["Reserved credits were refunded."],
        )


def _record_dispatch_deferred(task_id: str, exc: Exception) -> None:
    with _connect() as db:
        _ensure_schema(db)
        row = db.execute(
            "SELECT status FROM global_tasks WHERE id=?", (task_id,)
        ).fetchone()
        if not row or row["status"] != "queued":
            return
        _event(
            db,
            task_id,
            "task.dispatch_deferred",
            "Durable worker queue is unavailable; task remains queued for recovery.",
            {"error": type(exc).__name__},
        )
        db.commit()


def dispatch_cloud_task(task_id: str) -> None:
    """Dispatch to Celery; never downgrade production work to an ephemeral thread."""
    try:
        from amoscloud_ai.task_dispatch import dispatch_task
        from amoscloud_ai.worker import run_global_task

        dispatch_task(run_global_task, task_id)
    except Exception as exc:
        if _production():
            _record_dispatch_deferred(task_id, exc)
            return
        thread = threading.Thread(
            target=execute_cloud_task,
            args=(task_id,),
            name=f"amosclaud-task-{task_id[-8:]}",
            daemon=True,
        )
        thread.start()


def _age_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        started = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - started).total_seconds())


def recover_cloud_tasks(
    *,
    stale_seconds: int | None = None,
    limit: int = 100,
) -> dict[str, int]:
    """Requeue interrupted cloud/GitHub tasks and redispatch all durable queued work."""
    threshold = stale_seconds
    if threshold is None:
        threshold = int(os.getenv("AMOSCLAUD_OPERATION_STALE_SECONDS", "900"))
    threshold = max(60, min(int(threshold), 86_400))
    recovered = 0
    queued_ids: list[str] = []
    with _connect() as db:
        _ensure_schema(db)
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute(
            """SELECT id,status,started_at FROM global_tasks
               WHERE execution_target IN ('cloud','github')
                 AND status IN ('queued','running')
               ORDER BY created_at LIMIT ?""",
            (max(1, min(limit, 500)),),
        ).fetchall()
        for row in rows:
            task_id = str(row["id"])
            if row["status"] == "running":
                age = _age_seconds(row["started_at"])
                if age is not None and age < threshold:
                    continue
                db.execute(
                    """UPDATE global_tasks
                       SET status='queued',started_at=NULL
                       WHERE id=? AND status='running'""",
                    (task_id,),
                )
                _event(
                    db,
                    task_id,
                    "task.recovered",
                    "Recovered an interrupted operation and returned it to the durable queue.",
                    {"stale_seconds": age},
                )
                recovered += 1
            queued_ids.append(task_id)
        db.commit()
    for task_id in queued_ids:
        dispatch_cloud_task(task_id)
    return {"recovered": recovered, "dispatched": len(queued_ids)}
