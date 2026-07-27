"""Dedicated execution adapter for Autonomous Engineering Workforce delegations.

The runner is deliberately separate from the Daily Autonomous Builder so workforce
pull requests, branches, evidence, and lifecycle events describe delegated work
accurately. Both runners still use the same single Amosclaud engineering core and
the same isolated verification infrastructure.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import threading
from pathlib import Path

import httpx
from git import Repo

from amoscloud_ai.api.routes.github_repositories import (
    _authenticated_clone_url,
    _public_remote_url,
)
from amoscloud_ai.autonomous_builder import AutonomousPolicyError, path_policy_violations
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
from amoscloud_ai.engineering_workforce import record_delegation_task_event


_REQUIRED_TRUE = (
    "require_tests",
    "require_isolated_execution",
    "require_draft_pull_request",
    "require_human_merge",
    "require_rollback_checkpoint",
    "secret_masking",
    "production_deploy_requires_approval",
)
_REQUIRED_FALSE = (
    "force_push",
    "direct_protected_branch_write",
    "auto_merge",
)


def _metadata(task: dict) -> dict:
    value = task.get("metadata")
    if isinstance(value, dict):
        return value
    try:
        decoded = json.loads(task.get("metadata_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _safe_fragment(value: str, fallback: str) -> str:
    fragment = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "")).strip("-.")
    return (fragment or fallback)[:48]


def _validate_policy(policy: dict) -> None:
    if policy.get("engineering_workforce") is not True:
        raise AutonomousPolicyError("Workforce policy is missing from task metadata")
    for name in _REQUIRED_TRUE:
        if policy.get(name) is not True:
            raise AutonomousPolicyError(f"Workforce policy requires {name}=true")
    for name in _REQUIRED_FALSE:
        if policy.get(name) is not False:
            raise AutonomousPolicyError(f"Workforce policy requires {name}=false")
    if not policy.get("allowed_paths"):
        raise AutonomousPolicyError("Workforce policy has no authorized write paths")


def _enforce_paths(policy: dict, changed_files: list[str]) -> None:
    violations = path_policy_violations(
        changed_files,
        allowed_paths=list(policy.get("allowed_paths") or []),
        protected_paths=list(policy.get("protected_paths") or []),
    )
    if violations:
        raise AutonomousPolicyError(
            "Workforce guardrail blocked publication: " + "; ".join(violations[:8])
        )


def _work_title(task: dict, policy: dict) -> str:
    objective = str(task.get("objective") or "")
    for prefix in ("Work item: ", "Feature: ", "Objective: "):
        for line in objective.splitlines():
            if line.startswith(prefix) and line.removeprefix(prefix).strip():
                return line.removeprefix(prefix).strip()[:72]
    return str(policy.get("delegation_kind") or "engineering work").replace("_", " ").title()


def _pull_request_body(
    task: dict,
    policy: dict,
    evidence: list[str],
    *,
    base: str,
    base_sha: str,
    changed_files: list[str],
) -> str:
    criteria = []
    capture = False
    for line in str(task.get("objective") or "").splitlines():
        if line.strip() == "## Acceptance criteria":
            capture = True
            continue
        if capture and line.startswith("## "):
            break
        if capture and line.startswith("- "):
            criteria.append(line)
    criteria_text = "\n".join(criteria[:30]) or "- Acceptance criteria are recorded in the delegation."
    return (
        "Created by the Amosclaud Autonomous Engineering Workforce.\n\n"
        f"Delegation: {policy.get('delegation_id')}\n"
        f"Task: {task['id']}\n"
        f"Operation bucket: {task.get('bucket_id')}\n"
        f"Rollback checkpoint: `{base}` at `{base_sha}`\n\n"
        "## Acceptance criteria\n"
        f"{criteria_text}\n\n"
        "## Guardrail state\n"
        "- Isolated work branch\n"
        "- Protected-branch writes disabled\n"
        "- Force push disabled\n"
        "- Automatic merge disabled\n"
        "- Draft pull request only\n"
        "- Secret masking enabled\n"
        "- Deterministic isolated verification required\n"
        "- Human final sign-off required\n\n"
        "## Verified change set\n"
        + "\n".join(f"- `{path}`" for path in changed_files[:100])
        + f"\n\nVerification evidence records: {len(evidence)}"
    )[:60_000]


def _github_json(response: httpx.Response) -> dict:
    content_type = response.headers.get("content-type", "").lower()
    if "json" not in content_type:
        raise RuntimeError("GitHub returned a non-JSON pull-request response")
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("GitHub returned invalid pull-request JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub returned an invalid pull-request payload")
    return payload


def _bounded_change_loop(
    repo: Repo,
    root: Path,
    task: dict,
    policy: dict,
) -> tuple[list[str], list[str]]:
    max_attempts = max(1, min(int(policy.get("max_repair_attempts") or 1), 3))
    objective = str(task["objective"])
    diagnostic = ""
    evidence: list[str] = []

    for attempt in range(1, max_attempts + 1):
        attempt_objective = objective
        if diagnostic:
            attempt_objective += (
                "\n\nThe previous isolated verification failed. Correct the existing "
                "working tree without weakening tests, security checks, or guardrails.\n"
                "Failure evidence:\n" + diagnostic[-8_000:]
            )
        evidence.append(f"Workforce engineering attempt {attempt}/{max_attempts} started.")
        record_delegation_task_event(
            task["id"],
            "running",
            f"Engineering attempt {attempt}/{max_attempts} started.",
            {"attempt": attempt, "max_attempts": max_attempts},
        )
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
                raise RuntimeError("Delegated engineering task produced no repository changes")
            _enforce_paths(policy, changed_files)
            verification_evidence, _checks = _run_verification(root, changed_files)
            evidence.extend(f"attempt {attempt} · {item}" for item in verification_evidence)
            evidence.append(f"Workforce engineering attempt {attempt} passed.")
            return changed_files, evidence
        except AutonomousPolicyError:
            raise
        except (EngineeringAgentError, RuntimeError) as exc:
            diagnostic = str(exc)
            evidence.append(
                f"Workforce engineering attempt {attempt} failed: {type(exc).__name__}."
            )
            record_delegation_task_event(
                task["id"],
                "running",
                f"Attempt {attempt} failed verification; the bounded self-correction loop will continue when allowed.",
                {"attempt": attempt, "failure_type": type(exc).__name__},
            )
            if attempt >= max_attempts:
                raise RuntimeError(
                    f"Workforce verification failed after {max_attempts} bounded attempts"
                ) from exc
    raise RuntimeError("Workforce engineering loop ended without verified changes")


def _read_only_work(
    repo: Repo,
    root: Path,
    task: dict,
) -> tuple[str, list[str], str]:
    if task["mode"] == "test":
        evidence, _checks = _run_verification(root, [])
        summary = "Repository verification completed without repository mutation."
    else:
        run = run_engineering_agent(root, str(task["objective"]), apply_changes=False)
        evidence = [*run.evidence]
        evidence.extend(
            f"{check.get('name', 'check')}: {'passed' if check.get('passed') else 'failed'}"
            for check in run.checks
        )
        if any(not check.get("passed", False) for check in run.checks):
            raise RuntimeError("Read-only engineering review returned a blocking check")
        summary = run.summary or "Read-only engineering review completed."
    commit_sha = repo.head.commit.hexsha
    return summary, evidence, _verification_id(task["id"], commit_sha, evidence)


def execute_workforce_task(task_id: str) -> None:
    """Execute one delegated work order with bounded repair and a verified draft PR."""

    task = _start(task_id)
    if not task:
        return
    policy = _metadata(task)
    try:
        _validate_policy(policy)
    except AutonomousPolicyError as exc:
        summary = str(exc)[:20_000]
        _finish(task_id, "failed", summary, evidence=[summary])
        record_delegation_task_event(task_id, "blocked", summary)
        return

    record_delegation_task_event(
        task_id,
        "running",
        "The isolated Autonomous Engineering Workforce execution started.",
        {"execution_target": task.get("execution_target")},
    )
    tempdir: Path | None = None
    try:
        repository = _repository(task)
        tempdir = Path(tempfile.mkdtemp(prefix=f"amosclaud-workforce-{task_id}-"))
        token = repository.pop("token")
        base = (
            repository.get("github_default_branch")
            or repository.get("default_branch")
            or "main"
        )
        protected = {str(item).casefold() for item in policy.get("protected_branches") or []}
        if str(base).casefold() not in protected:
            protected.add(str(base).casefold())
        branch_prefix = _safe_fragment(policy.get("branch_prefix"), "amosclaud-workforce")
        delegation_fragment = _safe_fragment(policy.get("delegation_id"), task_id)[-24:]
        branch = f"{branch_prefix}/{delegation_fragment}"

        Repo.clone_from(
            _authenticated_clone_url(repository["github_full_name"], token),
            tempdir,
            branch=base,
            depth=1,
        )
        repo = Repo(tempdir)
        base_sha = repo.head.commit.hexsha
        repo.remote("origin").set_url(_public_remote_url(repository["github_full_name"]))
        if branch.casefold() in protected:
            raise AutonomousPolicyError("Generated workforce branch conflicts with a protected branch")
        repo.git.checkout("-b", branch)
        record_delegation_task_event(
            task_id,
            "running",
            "Rollback checkpoint recorded before repository mutation.",
            {"base": base, "base_sha": base_sha, "work_branch": branch},
        )

        if task["mode"] in {"test", "review"}:
            summary, evidence, verification_id = _read_only_work(repo, tempdir, task)
            artifacts = [
                {
                    "type": "rollback_checkpoint",
                    "base_branch": base,
                    "base_sha": base_sha,
                }
            ]
            _finish(
                task_id,
                "completed",
                summary,
                artifacts=artifacts,
                evidence=evidence,
                verification_id=verification_id,
            )
            record_delegation_task_event(
                task_id,
                "completed",
                summary,
                {"verification_id": verification_id},
            )
            return

        changed_files, evidence = _bounded_change_loop(repo, tempdir, task, policy)
        _enforce_paths(policy, changed_files)
        artifacts = [
            {
                "type": "rollback_checkpoint",
                "base_branch": base,
                "base_sha": base_sha,
                "work_branch": branch,
            }
        ]
        diff = repo.git.diff("HEAD", "--", ".")
        artifacts.append(
            {
                "type": "patch",
                "name": f"{task_id}.patch",
                "content": diff[:200_000],
            }
        )

        repo.git.add(A=True)
        with repo.config_writer() as config:
            config.set_value("user", "name", "Amosclaud Autonomous Workforce")
            config.set_value("user", "email", "workforce@amosclaud.com")
        repo.index.commit(f"Amosclaud workforce: {_work_title(task, policy)}")

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
                "title": f"Amosclaud workforce: {_work_title(task, policy)}",
                "head": branch,
                "base": base,
                "draft": True,
                "body": _pull_request_body(
                    task,
                    policy,
                    evidence,
                    base=base,
                    base_sha=base_sha,
                    changed_files=changed_files,
                ),
            },
            timeout=30,
        )
        response.raise_for_status()
        pull_request = _github_json(response)
        pull_request_url = str(pull_request.get("html_url") or "")
        if not pull_request_url.startswith("https://github.com/"):
            raise RuntimeError("GitHub pull-request response did not include a safe URL")
        artifacts.append({"type": "pull_request", "url": pull_request_url, "draft": True})

        commit_sha = repo.head.commit.hexsha
        verification_id = _verification_id(task_id, commit_sha, evidence)
        artifacts.append(
            {
                "type": "verification",
                "verification_id": verification_id,
                "commit_sha": commit_sha,
            }
        )
        summary = "Delegated engineering work completed with a verified draft pull request."
        _finish(
            task_id,
            "completed",
            summary,
            artifacts=artifacts,
            pull_request_url=pull_request_url,
            evidence=evidence,
            verification_id=verification_id,
        )
        record_delegation_task_event(
            task_id,
            "completed",
            summary,
            {
                "pull_request_url": pull_request_url,
                "verification_id": verification_id,
                "base_sha": base_sha,
                "commit_sha": commit_sha,
            },
        )
    except AutonomousPolicyError as exc:
        summary = str(exc)[:20_000]
        _finish(task_id, "failed", summary, evidence=[summary])
        record_delegation_task_event(task_id, "blocked", summary)
    except Exception as exc:
        summary = f"Autonomous workforce execution stopped safely: {type(exc).__name__}"
        _finish(task_id, "failed", summary, evidence=["No protected branch was modified."])
        record_delegation_task_event(
            task_id,
            "failed",
            summary,
            {"failure_type": type(exc).__name__},
        )
    finally:
        if tempdir is not None:
            shutil.rmtree(tempdir, ignore_errors=True)


def _is_workforce_task(task_id: str) -> bool:
    from amoscloud_ai.api.routes.auth import _connect
    from amoscloud_ai.api.routes.task_router import _ensure_schema

    with _connect() as db:
        _ensure_schema(db)
        row = db.execute(
            "SELECT metadata_json FROM global_tasks WHERE id=?",
            (task_id,),
        ).fetchone()
    if not row:
        return False
    try:
        metadata = json.loads(row["metadata_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        return False
    return isinstance(metadata, dict) and metadata.get("engineering_workforce") is True


def dispatch_workforce_task(task_id: str) -> None:
    if not _is_workforce_task(task_id):
        raise AutonomousPolicyError("Refused to dispatch a non-workforce task")
    try:
        from amoscloud_ai.task_dispatch import dispatch_task
        from amoscloud_ai.worker import run_workforce_task

        dispatch_task(run_workforce_task, task_id)
    except Exception as exc:
        if _production():
            _record_dispatch_deferred(task_id, exc)
            return
        thread = threading.Thread(
            target=execute_workforce_task,
            args=(task_id,),
            name=f"amosclaud-workforce-{task_id[-8:]}",
            daemon=True,
        )
        thread.start()


def install_workforce_dispatch_hook() -> None:
    """Route only workforce-tagged tasks through the governed workforce runner."""

    from amoscloud_ai import cloud_task_runner

    current = cloud_task_runner.dispatch_cloud_task
    if getattr(current, "_amosclaud_workforce_router", False):
        return

    def routed_dispatch(task_id: str) -> None:
        if _is_workforce_task(task_id):
            dispatch_workforce_task(task_id)
        else:
            current(task_id)

    routed_dispatch._amosclaud_workforce_router = True  # type: ignore[attr-defined]
    cloud_task_runner.dispatch_cloud_task = routed_dispatch
