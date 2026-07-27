"""Policy-enforced execution adapter for Daily Autonomous Builder tasks."""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
from pathlib import Path

import httpx
from git import Repo
from git.exc import GitCommandError

from amoscloud_ai.api.routes.github_repositories import (
    _authenticated_clone_url,
    _public_remote_url,
)
from amoscloud_ai.autonomous_builder import (
    AutonomousPolicyError,
    enforce_task_path_policy,
    record_task_completion,
    record_task_started,
    task_policy,
)
from amoscloud_ai.cloud_task_runner import (
    _assert_base_unchanged,
    _changed_paths,
    _finish,
    _production,
    _record_dispatch_deferred,
    _repository,
    _run_verification,
    _start,
    _verification_id,
)
from amoscloud_ai.engineering_agent import EngineeringAgentError, run_engineering_agent


def _pull_request_body(task: dict, policy: dict, evidence: list[str]) -> str:
    return (
        "Created by the Amosclaud Daily Autonomous Builder.\n\n"
        f"Autonomous run: {policy.get('autonomous_run_id')}\n"
        f"Backlog item: {policy.get('autonomous_backlog_id')}\n"
        f"Task: {task['id']}\n"
        f"Bucket: {task['bucket_id']}\n\n"
        "Safety state:\n"
        "- Draft pull request only\n"
        "- Direct main-branch writes disabled\n"
        "- Automatic merge disabled\n"
        "- Account path policy enforced before publication\n"
        "- Deterministic isolated verification required\n\n"
        f"Verification evidence records: {len(evidence)}"
    )


def _bounded_engineering_loop(
    repo: Repo,
    root: Path,
    task: dict,
    policy: dict,
) -> tuple[list[str], list[str]]:
    """Apply, diagnose, and correct within the account's fixed attempt limit."""

    max_attempts = max(1, min(int(policy.get("max_repair_attempts") or 1), 3))
    objective = str(task["objective"])
    diagnostic = ""
    evidence: list[str] = []
    successful_paths: list[str] = []

    for attempt in range(1, max_attempts + 1):
        attempt_objective = objective
        if diagnostic:
            attempt_objective += (
                "\n\nThe previous isolated verification attempt failed. "
                "Correct the existing working tree without weakening tests or policy.\n"
                "Failure evidence:\n" + diagnostic[-8_000:]
            )
        evidence.append(f"Autonomous engineering attempt {attempt}/{max_attempts} started.")
        try:
            run = run_engineering_agent(root, attempt_objective, apply_changes=True)
            evidence.extend(run.evidence)
            evidence.extend(
                f"attempt {attempt} · {check.get('name', 'check')}: "
                f"{'passed' if check.get('passed') else 'failed'}"
                for check in run.checks
            )
            if any(not check.get("passed", False) for check in run.checks):
                raise RuntimeError("Engineering checks failed before isolated verification")

            changed_files = _changed_paths(repo)
            if not changed_files:
                raise RuntimeError("Autonomous feature task produced no repository changes")
            enforce_task_path_policy(task, changed_files)
            verification_evidence, _checks = _run_verification(root, changed_files)
            evidence.extend(
                f"attempt {attempt} · {item}" for item in verification_evidence
            )
            evidence.append(f"Autonomous engineering attempt {attempt} passed.")
            successful_paths = changed_files
            break
        except AutonomousPolicyError:
            raise
        except (EngineeringAgentError, RuntimeError) as exc:
            diagnostic = str(exc)
            evidence.append(
                f"Autonomous engineering attempt {attempt} failed: {type(exc).__name__}."
            )
            if attempt >= max_attempts:
                raise RuntimeError(
                    f"Autonomous verification failed after {max_attempts} bounded attempts"
                ) from exc

    if not successful_paths:
        raise RuntimeError("Autonomous engineering loop ended without verified changes")
    return successful_paths, evidence


def execute_autonomous_task(task_id: str) -> None:
    """Execute one queued autonomous build with pre-publication policy checks."""

    task = _start(task_id)
    if not task:
        return
    policy = task_policy(task)
    if not policy:
        _finish(
            task_id,
            "failed",
            "Autonomous policy blocked publication: task metadata is missing.",
            evidence=["No autonomous policy metadata was available."],
        )
        return
    if policy.get("auto_merge") is not False:
        summary = "Autonomous policy blocked publication: auto_merge must be false."
        _finish(task_id, "failed", summary, evidence=[summary])
        record_task_completion(task_id, "failed", summary)
        return

    record_task_started(task_id)
    tempdir: Path | None = None
    try:
        repository = _repository(task)
        tempdir = Path(tempfile.mkdtemp(prefix=f"amosclaud-daily-{task_id}-"))
        token = repository.pop("token")
        base = (
            repository.get("github_default_branch")
            or repository.get("default_branch")
            or "main"
        )
        run_fragment = str(policy.get("autonomous_run_id") or task_id).replace("_", "-")[-20:]
        branch = f"amosclaud/daily-{run_fragment}"

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

        changed_files, evidence = _bounded_engineering_loop(repo, tempdir, task, policy)
        enforce_task_path_policy(task, changed_files)

        diff = repo.git.diff("HEAD", "--", ".")
        artifacts = [
            {
                "type": "patch",
                "name": f"{task_id}.patch",
                "content": diff[:200_000],
            }
        ]

        repo.git.add(A=True)
        with repo.config_writer() as config:
            config.set_value("user", "name", "Amosclaud Daily Builder")
            config.set_value("user", "email", "daily-builder@amosclaud.com")
        repo.index.commit(f"Amosclaud daily feature: {task['objective'][:64]}")

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

        feature_title = task["objective"].splitlines()[2]
        response = httpx.post(
            f"https://api.github.com/repos/{repository['github_full_name']}/pulls",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={
                "title": f"Amosclaud daily: {feature_title[:72]}",
                "head": branch,
                "base": base,
                "draft": True,
                "body": _pull_request_body(task, policy, evidence),
            },
            timeout=30,
        )
        response.raise_for_status()
        pull_request_url = str(response.json()["html_url"])
        artifacts.append({"type": "pull_request", "url": pull_request_url})

        commit_sha = repo.head.commit.hexsha
        verification_id = _verification_id(task_id, commit_sha, evidence)
        artifacts.append(
            {
                "type": "verification",
                "verification_id": verification_id,
                "commit_sha": commit_sha,
            }
        )
        summary = "Daily autonomous feature completed with a verified draft pull request."
        _finish(
            task_id,
            "completed",
            summary,
            artifacts=artifacts,
            pull_request_url=pull_request_url,
            evidence=evidence,
            verification_id=verification_id,
        )
        record_task_completion(
            task_id,
            "completed",
            summary,
            pull_request_url=pull_request_url,
            verification_id=verification_id,
        )
    except AutonomousPolicyError as exc:
        summary = str(exc)[:20_000]
        _finish(task_id, "failed", summary, evidence=[summary])
        record_task_completion(task_id, "failed", summary)
    except (GitCommandError, httpx.HTTPError, EngineeringAgentError, RuntimeError) as exc:
        summary = f"Autonomous execution stopped safely: {type(exc).__name__}"
        _finish(task_id, "failed", summary, evidence=["Reserved credits were refunded."])
        record_task_completion(task_id, "failed", summary)
    finally:
        if tempdir is not None:
            shutil.rmtree(tempdir, ignore_errors=True)


def _is_autonomous_task(task_id: str) -> bool:
    from amoscloud_ai.api.routes.auth import _connect
    from amoscloud_ai.api.routes.task_router import _ensure_schema

    with _connect() as db:
        _ensure_schema(db)
        row = db.execute(
            "SELECT metadata_json FROM global_tasks WHERE id=?", (task_id,)
        ).fetchone()
    if not row:
        return False
    try:
        metadata = json.loads(row["metadata_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        return False
    return isinstance(metadata, dict) and metadata.get("autonomous_builder") is True


def dispatch_autonomous_task(task_id: str) -> None:
    """Dispatch durably in production and use a daemon thread only in development."""

    if not _is_autonomous_task(task_id):
        raise AutonomousPolicyError("Refused to dispatch a non-autonomous task")
    try:
        from amoscloud_ai.task_dispatch import dispatch_task
        from amoscloud_ai.worker import run_autonomous_feature_task

        dispatch_task(run_autonomous_feature_task, task_id)
    except Exception as exc:
        if _production():
            _record_dispatch_deferred(task_id, exc)
            return
        thread = threading.Thread(
            target=execute_autonomous_task,
            args=(task_id,),
            name=f"amosclaud-daily-{task_id[-8:]}",
            daemon=True,
        )
        thread.start()


def install_dispatch_hook() -> None:
    """Route only tagged autonomous tasks away from the general cloud runner."""

    from amoscloud_ai import cloud_task_runner

    current = cloud_task_runner.dispatch_cloud_task
    if getattr(current, "_amosclaud_autonomy_router", False):
        return

    def routed_dispatch(task_id: str) -> None:
        if _is_autonomous_task(task_id):
            dispatch_autonomous_task(task_id)
        else:
            current(task_id)

    routed_dispatch._amosclaud_autonomy_router = True  # type: ignore[attr-defined]
    cloud_task_runner.dispatch_cloud_task = routed_dispatch
