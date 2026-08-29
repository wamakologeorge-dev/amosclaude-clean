"""Durable, fixed-plan Amosclaud Actions for native pull requests.

This module deliberately does not inspect package scripts, workflow files, or any
other repository-controlled command configuration.  The only executable plan is
compileall, a code-owned bootstrap that installs the repository's declared
requirements into a fresh per-run environment, then pytest — each run in the
existing isolated runner. The bootstrap honors standard Python packaging
manifests only (requirements files, pyproject/setup), never repository-chosen
commands.
"""

from __future__ import annotations

import logging
import re
import shutil
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from git import Repo

from amoscloud_ai.api.routes import pipelines
from amoscloud_ai.api.routes.repositories import _db, _repo_path
from amoscloud_ai.isolated_runner import IsolatedRunResult, redact_output, run_in_isolated_container
from amoscloud_ai.models import PipelineJob, PipelineResponse, PipelineStatus
from amoscloud_ai.task_dispatch import dispatch_task

_LOGGER = logging.getLogger(__name__)
_ACTION_SHA = re.compile(r"^[0-9a-f]{40}$")
# This plan is intentionally code-owned. Do not replace it with repository input.
DEPS_FILE_SIZE_LIMIT_BYTES = 1024**3
"""Installing a repository's declared requirements downloads real wheels, so
the deps step gets a one-gigabyte per-file allowance instead of the runner's
strict default. Compile and pytest steps keep the strict cap."""

ACTION_PLAN: tuple[tuple[str, str, str], ...] = (
    ("compileall", "Compile Python sources", "python -m compileall -q -x [.]amosclaud-venv ."),
    ("deps", "Install repository requirements", "python .amosclaud-bootstrap.py"),
    ("pytest", "Run pytest", ".amosclaud-venv/bin/python -m pytest -q"),
)

# Plain-language meanings for pytest's documented exit codes so a failed
# Amosclaud Action tells a normal user what actually happened instead of a
# bare integer. https://docs.pytest.org/en/stable/reference/exit-codes.html
PYTEST_EXIT_MEANINGS: dict[int, str] = {
    1: "tests ran and at least one test failed",
    2: "test collection or execution was interrupted before it finished",
    3: "pytest itself hit an internal error",
    4: (
        "pytest could not start because the repository's test configuration "
        "needs a dependency or option the worker station does not provide"
    ),
    5: "pytest started but found no tests to run",
}


def _failure_detail(job: PipelineJob, result: IsolatedRunResult) -> str:
    """Concise, truthful failure summary for the stored incident record."""
    detail = f"{job.name} returned {result.returncode}"
    if result.timed_out:
        return detail + " (timed out)"
    meaning = PYTEST_EXIT_MEANINGS.get(result.returncode) if job.id == "pytest" else None
    if meaning is not None:
        detail += f" — {meaning}. The execution log records the exact cause."
    elif job.id == "deps":
        detail += (
            " — the repository's declared requirements could not be installed on the "
            "worker station. The execution log records pip's exact message."
        )
    return detail


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_schema(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS native_action_runs (
            id TEXT PRIMARY KEY,
            repository_id INTEGER NOT NULL,
            pull_request_id INTEGER NOT NULL,
            head_sha TEXT NOT NULL,
            branch TEXT NOT NULL,
            requested_by INTEGER NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            action_ref TEXT,
            status TEXT NOT NULL CHECK(status IN ('pending','queued','running','success','failed','cancelled')),
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            error_detail TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(repository_id) REFERENCES repositories(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_native_action_pr_history
            ON native_action_runs(repository_id, pull_request_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_native_action_recovery
            ON native_action_runs(status, created_at);
        """)
    db.commit()


def ensure_schema(db: sqlite3.Connection) -> None:
    """Public helper for migrations and route startup."""
    _ensure_schema(db)


def _action_pipeline(
    action_id: str,
    branch: str,
    status: PipelineStatus,
    created_at: datetime,
    *,
    message: str,
    finished_at: datetime | None = None,
    jobs: list[PipelineJob] | None = None,
) -> PipelineResponse:
    return PipelineResponse(
        id=action_id,
        status=status,
        trigger="amosclaud-ci",
        branch=branch,
        started_at=created_at,
        finished_at=finished_at,
        message=message,
        copilot_reply=message,
        copilot_role="Amosclaud Actions",
        delegation_target="native-isolated-runner",
        jobs=(
            jobs
            if jobs is not None
            else [
                PipelineJob(id=job_id, name=name, status=PipelineStatus.QUEUED, logs=[])
                for job_id, name, _ in ACTION_PLAN
            ]
        ),
    )


def _payload(
    repository_id: int, pull_request_id: int, sha: str, requested_by: int, reason: str
) -> dict[str, Any]:
    return {
        "repository_id": repository_id,
        "pull_request_id": pull_request_id,
        "authoritative": True,
        "commit_sha": sha,
        "requested_by": requested_by,
        "reason": reason,
        "native_action": True,
        "fixed_plan": [command for _, _, command in ACTION_PLAN],
    }


def _save_pipeline(
    pipeline: PipelineResponse, payload: dict[str, Any], error_detail: str = ""
) -> None:
    # The established pipeline store supplies the compatibility API and persists
    # job logs. Native attribution is additionally in native_action_runs.
    pipelines._save(
        pipeline,
        {
            "trigger": "amosclaud-ci",
            "branch": pipeline.branch,
            "commit_sha": payload["commit_sha"],
            "payload": payload,
        },
        error_detail,
    )


def _update_action(
    action_id: str,
    *,
    status: PipelineStatus,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    error_detail: str = "",
) -> None:
    with _db() as db:
        _ensure_schema(db)
        db.execute(
            """UPDATE native_action_runs SET status=?, started_at=COALESCE(?, started_at),
               finished_at=COALESCE(?, finished_at), error_detail=? WHERE id=?""",
            (
                status.value,
                started_at.isoformat() if started_at else None,
                finished_at.isoformat() if finished_at else None,
                error_detail[:20_000],
                action_id,
            ),
        )
        db.commit()


def _pin_action_ref(repository_id: int, action_ref: str, sha: str) -> Repo:
    """Create the private immutable ref before the Action becomes dispatchable."""
    repo = Repo(_repo_path(repository_id))
    resolved = repo.commit(sha).hexsha.lower()
    if resolved != sha:
        raise RuntimeError("Action revision is not an exact repository commit")
    repo.git.update_ref(action_ref, sha)
    return repo


def _delete_action_ref(repo: Repo | None, action_ref: str | None) -> None:
    """Best-effort cleanup; the durable record remains available for audit."""
    if repo is not None and action_ref:
        try:
            repo.git.update_ref("-d", action_ref)
        except Exception as exc:
            _LOGGER.warning("Could not release native Action ref (%s).", type(exc).__name__)


def queue_action(
    *,
    repository_id: int,
    pull_request_id: int,
    branch: str,
    head_sha: str,
    requested_by: int,
    reason: str,
) -> PipelineResponse:
    """Pin, persist, and then dispatch one native Action.

    The ref is created before the row can be claimed, so a moving branch can
    never change the revision that the worker checks out. If persistence fails,
    the just-created ref is removed because no durable Action owns it.
    """
    sha = head_sha.lower()
    if not _ACTION_SHA.fullmatch(sha):
        raise ValueError("Native Action requires a full immutable commit SHA")
    action_id = str(uuid.uuid4())
    action_ref = f"refs/amosclaud/actions/{action_id}"
    created_at = _now()
    payload = _payload(repository_id, pull_request_id, sha, requested_by, reason)
    pipeline = _action_pipeline(
        action_id,
        branch,
        PipelineStatus.QUEUED,
        created_at,
        message="Amosclaud Action queued for the isolated worker.",
    )
    repo = _pin_action_ref(repository_id, action_ref, sha)
    try:
        with _db() as db:
            _ensure_schema(db)
            db.execute(
                """INSERT INTO native_action_runs(
                   id,repository_id,pull_request_id,head_sha,branch,requested_by,
                   reason,action_ref,status,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    action_id,
                    repository_id,
                    pull_request_id,
                    sha,
                    branch,
                    requested_by,
                    reason[:500],
                    action_ref,
                    "queued",
                    created_at.isoformat(),
                ),
            )
            db.commit()
    except Exception:
        _delete_action_ref(repo, action_ref)
        raise
    try:
        _save_pipeline(pipeline, payload)
    except Exception as exc:
        _mark_queue_unavailable(action_id, pipeline, payload, type(exc).__name__)
        raise
    try:
        from amoscloud_ai.worker import run_native_action_task

        dispatch_task(run_native_action_task, action_id)
    except Exception as exc:
        _mark_queue_unavailable(action_id, pipeline, payload, type(exc).__name__)
    return pipeline


def _mark_queue_unavailable(
    action_id: str, pipeline: PipelineResponse, payload: dict[str, Any], exception_name: str
) -> None:
    """Make a failed broker hand-off visible instead of leaving fake queued CI."""
    finished_at = _now()
    detail = f"Worker queue unavailable: {exception_name}"
    pipeline.status = PipelineStatus.FAILED
    pipeline.finished_at = finished_at
    pipeline.message = "Amosclaud Action was not queued because the worker queue is unavailable."
    pipeline.copilot_reply = pipeline.message
    for job in pipeline.jobs:
        job.status = PipelineStatus.FAILED
        job.finished_at = finished_at
        job.logs.append(detail)
    _update_action(
        action_id, status=PipelineStatus.FAILED, finished_at=finished_at, error_detail=detail
    )
    _cleanup_terminal_action_ref(action_id)
    _save_pipeline(pipeline, payload, detail)


def _action_row(action_id: str) -> sqlite3.Row | None:
    with _db() as db:
        _ensure_schema(db)
        return db.execute("SELECT * FROM native_action_runs WHERE id=?", (action_id,)).fetchone()


def _cleanup_terminal_action_ref(action_id: str) -> None:
    """Release a queue-time ref only after its Action has reached a terminal state."""
    action = _action_row(action_id)
    if action is None or not action["action_ref"]:
        return
    try:
        _delete_action_ref(Repo(_repo_path(int(action["repository_id"]))), action["action_ref"])
    except Exception as exc:
        # Failed cleanup must not turn an already recorded terminal outcome
        # into a misleading non-terminal Action. Recovery will retry it.
        _LOGGER.warning("Could not clean up terminal Action ref (%s).", type(exc).__name__)


def _safe_log(output: str) -> str:
    # The isolated runner redacts configured environment values. Keep a second
    # bounded sanitation layer so API logs cannot contain NUL/control escapes.
    cleaned = redact_output(output or "", [])
    return "".join(char if char in "\n\t" or ord(char) >= 32 else "�" for char in cleaned)[
        :2_000_000
    ]


def _detached_checkout(
    repository_id: int, action_ref: str, sha: str
) -> tuple[Repo, Path, str, Path]:
    """Create a disposable checkout from the exact queue-time-pinned ref."""
    source = _repo_path(repository_id)
    repo = Repo(source)
    resolved = repo.commit(action_ref).hexsha.lower()
    if resolved != sha:
        raise RuntimeError("Action ref does not resolve to its stored immutable commit")
    temp_root = Path(tempfile.mkdtemp(prefix="amosclaud-action-"))
    checkout = temp_root / "checkout"
    try:
        # A real clone, never a worktree. A worktree's ``.git`` is a pointer
        # file, and real repositories legitimately treat ``.git`` as the
        # directory every genuine clone provides — George's suite stores its
        # brain state under ``.git/amosclaud-brain`` and failed with
        # NotADirectoryError on the worktree shape. A local clone shares
        # objects cheaply and the detached checkout pins the exact
        # queue-time commit.
        clone = Repo.clone_from(str(source), str(checkout), no_checkout=True)
        clone.git.checkout("--detach", sha)
        # The bootstrap is code-owned platform source copied in after checkout,
        # so repository content can never substitute its own version.
        shutil.copyfile(
            Path(__file__).with_name("action_bootstrap.py"),
            checkout / ".amosclaud-bootstrap.py",
        )
    except Exception:
        # The ref has durable ownership and is released only after the caller
        # records a terminal result in its cleanup path.
        shutil.rmtree(temp_root, ignore_errors=True)
        raise
    return repo, checkout, action_ref, temp_root


def _remove_checkout(
    _repo: Repo | None, checkout: Path | None, _ref: str | None, temp_root: Path | None
) -> None:
    """Remove the disposable clone without releasing the durable Action ref."""
    if temp_root is not None:
        shutil.rmtree(temp_root, ignore_errors=True)
    elif checkout is not None:
        shutil.rmtree(checkout, ignore_errors=True)


def _claim_queued_action(action_id: str) -> sqlite3.Row | None:
    """Atomically transition exactly one queued Action to running."""
    started_at = _now()
    with _db() as db:
        _ensure_schema(db)
        claimed = db.execute(
            """UPDATE native_action_runs
               SET status='running', started_at=COALESCE(started_at, ?)
               WHERE id=? AND status='queued'""",
            (started_at.isoformat(), action_id),
        )
        if claimed.rowcount != 1:
            db.rollback()
            return None
        row = db.execute("SELECT * FROM native_action_runs WHERE id=?", (action_id,)).fetchone()
        db.commit()
        return row


def cancel_action(action_id: str) -> PipelineResponse | None:
    """Cancel a queued or running Action and preserve a durable user-visible result.

    Running isolated commands finish their current non-interruptible process safely;
    no later fixed-plan step is started after cancellation is recorded.
    """
    finished_at = _now()
    with _db() as db:
        _ensure_schema(db)
        row = db.execute("SELECT * FROM native_action_runs WHERE id=?", (action_id,)).fetchone()
        if row is None:
            return None
        changed = db.execute(
            """UPDATE native_action_runs SET status='cancelled', finished_at=?,
               error_detail='Cancelled by an authorized Amosclaud user'
               WHERE id=? AND status IN ('queued','running')""",
            (finished_at.isoformat(), action_id),
        )
        if changed.rowcount != 1:
            db.rollback()
            return pipelines._get(action_id)
        db.commit()
    pipeline = pipelines._get(action_id)
    if pipeline is not None:
        pipeline.status = PipelineStatus.CANCELLED
        pipeline.finished_at = finished_at
        pipeline.message = "Amosclaud Action was cancelled by an authorized user."
        pipeline.copilot_reply = pipeline.message
        for job in pipeline.jobs:
            if job.status in {
                PipelineStatus.PENDING,
                PipelineStatus.QUEUED,
                PipelineStatus.RUNNING,
            }:
                job.status = PipelineStatus.CANCELLED
                job.finished_at = finished_at
                job.logs.append("Cancelled by an authorized Amosclaud user.")
        _save_pipeline(
            pipeline, _payload_for_action(row), "Cancelled by an authorized Amosclaud user"
        )
    _cleanup_terminal_action_ref(action_id)
    return pipeline


def _was_cancelled(action_id: str) -> bool:
    row = _action_row(action_id)
    return row is not None and row["status"] == PipelineStatus.CANCELLED.value


def execute_action(action_id: str) -> PipelineResponse | None:
    """Worker entry point. Only an atomically claimed queued Action can run."""
    row = _claim_queued_action(action_id)
    if row is None:
        # Duplicate queue deliveries, legacy pending records, in-progress rows,
        # and final Actions are all deliberately no-ops.
        return pipelines._get(action_id)
    created_at = datetime.fromisoformat(row["created_at"])
    payload = _payload(
        int(row["repository_id"]),
        int(row["pull_request_id"]),
        row["head_sha"],
        int(row["requested_by"]),
        row["reason"],
    )
    jobs = [
        PipelineJob(id=job_id, name=name, status=PipelineStatus.QUEUED, logs=[])
        for job_id, name, _ in ACTION_PLAN
    ]
    pipeline = _action_pipeline(
        action_id,
        row["branch"],
        PipelineStatus.RUNNING,
        created_at,
        message="Amosclaud Action is running in an isolated checkout.",
        jobs=jobs,
    )
    repo: Repo | None = None
    checkout: Path | None = None
    ref: str | None = None
    temp_root: Path | None = None
    try:
        _save_pipeline(pipeline, payload)
        repo, checkout, ref, temp_root = _detached_checkout(
            int(row["repository_id"]), row["action_ref"], row["head_sha"]
        )
        for job, (plan_id, _, command) in zip(pipeline.jobs, ACTION_PLAN):
            if _was_cancelled(action_id):
                return pipelines._get(action_id)
            job.status = PipelineStatus.RUNNING
            job.started_at = _now()
            job.logs.append(f"Started fixed Amosclaud Action step: {job.name}.")
            _save_pipeline(pipeline, payload)
            result: IsolatedRunResult = run_in_isolated_container(
                command,
                workspace=checkout,
                environment={"PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"},
                # Installing declared dependencies legitimately writes large
                # wheels; every other fixed step keeps the strict default cap.
                file_size_limit_bytes=(
                    DEPS_FILE_SIZE_LIMIT_BYTES if plan_id == "deps" else None
                ),
            )
            job.logs.append(_safe_log(result.output))
            job.finished_at = _now()
            if _was_cancelled(action_id):
                return pipelines._get(action_id)
            if result.returncode != 0 or result.timed_out:
                job.status = PipelineStatus.FAILED
                for remaining in pipeline.jobs[pipeline.jobs.index(job) + 1 :]:
                    remaining.status = PipelineStatus.CANCELLED
                    remaining.finished_at = job.finished_at
                    remaining.logs.append("Not run because an earlier fixed Action step failed.")
                pipeline.status = PipelineStatus.FAILED
                pipeline.finished_at = job.finished_at
                pipeline.message = f"Amosclaud Action failed during {job.name}."
                pipeline.copilot_reply = pipeline.message
                detail = _failure_detail(job, result)
                _update_action(
                    action_id,
                    status=PipelineStatus.FAILED,
                    finished_at=pipeline.finished_at,
                    error_detail=detail,
                )
                _cleanup_terminal_action_ref(action_id)
                _save_pipeline(pipeline, payload, detail)
                return pipeline
            job.status = PipelineStatus.SUCCESS
        pipeline.status = PipelineStatus.SUCCESS
        pipeline.finished_at = _now()
        pipeline.message = (
            "Amosclaud Action passed the fixed isolated plan: sources compiled, "
            "repository requirements installed, pytest green."
        )
        pipeline.copilot_reply = pipeline.message
        _update_action(action_id, status=PipelineStatus.SUCCESS, finished_at=pipeline.finished_at)
        _cleanup_terminal_action_ref(action_id)
        _save_pipeline(pipeline, payload)
        return pipeline
    except Exception as exc:
        finished_at = _now()
        detail = f"Native Action execution failed safely: {type(exc).__name__}"
        pipeline.status = PipelineStatus.FAILED
        pipeline.finished_at = finished_at
        pipeline.message = detail
        pipeline.copilot_reply = detail
        for job in pipeline.jobs:
            if job.status in {
                PipelineStatus.PENDING,
                PipelineStatus.QUEUED,
                PipelineStatus.RUNNING,
            }:
                job.status = PipelineStatus.FAILED
                job.finished_at = finished_at
                job.logs.append(detail)
        _update_action(
            action_id, status=PipelineStatus.FAILED, finished_at=finished_at, error_detail=detail
        )
        _cleanup_terminal_action_ref(action_id)
        _save_pipeline(pipeline, payload, detail)
        return pipeline
    finally:
        _remove_checkout(repo, checkout, ref, temp_root)


def _post_run_incident(
    row: sqlite3.Row, pipeline: PipelineResponse | None
) -> dict[str, Any] | None:
    """Return concise, stored-evidence-only follow-up for terminal bad outcomes."""
    outcome = str(row["status"])
    if outcome not in {PipelineStatus.FAILED.value, PipelineStatus.CANCELLED.value}:
        return None

    step: dict[str, str] | None = None
    if pipeline is not None:
        failed_job = next(
            (job for job in pipeline.jobs if job.status is PipelineStatus.FAILED),
            None,
        )
        if failed_job is not None:
            step = {"id": failed_job.id, "name": failed_job.name, "status": failed_job.status.value}
    detail = str(row["error_detail"] or "").strip()
    if detail:
        # Keep the follow-up record scannable; full execution evidence remains
        # in the existing pipeline log projection.
        summary = detail[:500]
    elif step is not None:
        summary = f"{step['name']} did not complete successfully."
    elif outcome == PipelineStatus.CANCELLED.value:
        summary = "Action was cancelled before completion."
    else:
        summary = "Action failed without a recorded error detail."
    return {
        "type": "post_run_incident",
        "outcome": outcome,
        "summary": summary,
        "occurred_at": row["finished_at"],
        "head_sha": row["head_sha"],
        "step": step,
    }


def action_history(repository_id: int, pull_request_id: int) -> list[dict[str, Any]]:
    with _db() as db:
        _ensure_schema(db)
        rows = db.execute(
            """SELECT * FROM native_action_runs WHERE repository_id=? AND pull_request_id=?
               ORDER BY created_at DESC""",
            (repository_id, pull_request_id),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        pipeline = pipelines._get(row["id"])
        item = dict(row)
        # This is an internal retention ref, not a client-facing branch name.
        item.pop("action_ref", None)
        item["pipeline"] = pipeline.model_dump(mode="json") if pipeline else None
        # Failed or cancelled native Actions carry a compact, evidence-only
        # incident record for the PR UI and API consumers. Successful runs do
        # not receive a synthetic incident.
        item["incident"] = _post_run_incident(row, pipeline)
        result.append(item)
    return result


def latest_action(repository_id: int, pull_request_id: int) -> dict[str, Any] | None:
    history = action_history(repository_id, pull_request_id)
    return history[0] if history else None


def _payload_for_action(row: sqlite3.Row) -> dict[str, Any]:
    return _payload(
        int(row["repository_id"]),
        int(row["pull_request_id"]),
        row["head_sha"],
        int(row["requested_by"]),
        row["reason"],
    )


def _mark_interrupted(action: sqlite3.Row, pipeline: PipelineResponse | None) -> None:
    """Complete both durable projections if a worker died during an Action."""
    finished_at = _now()
    detail = "Worker restarted before action completion"
    _update_action(
        action["id"], status=PipelineStatus.FAILED, finished_at=finished_at, error_detail=detail
    )
    _cleanup_terminal_action_ref(action["id"])
    if pipeline is None:
        return
    pipeline.status = PipelineStatus.FAILED
    pipeline.finished_at = finished_at
    pipeline.message = detail
    pipeline.copilot_reply = detail
    for job in pipeline.jobs:
        if job.status in {PipelineStatus.PENDING, PipelineStatus.QUEUED, PipelineStatus.RUNNING}:
            job.status = PipelineStatus.FAILED
            job.finished_at = finished_at
            job.logs.append(detail)
    _save_pipeline(pipeline, _payload_for_action(action), detail)


def _mark_unrecoverable_legacy_pending(action: sqlite3.Row) -> None:
    """Do not execute pre-ref rows against a branch that may have moved."""
    finished_at = _now()
    detail = "Legacy pending Action has no queue-time pinned ref; not requeued safely"
    _update_action(
        action["id"], status=PipelineStatus.FAILED, finished_at=finished_at, error_detail=detail
    )
    _cleanup_terminal_action_ref(action["id"])
    pipeline = pipelines._get(action["id"])
    if pipeline is None:
        return
    pipeline.status = PipelineStatus.FAILED
    pipeline.finished_at = finished_at
    pipeline.message = detail
    pipeline.copilot_reply = detail
    for job in pipeline.jobs:
        if job.status in {PipelineStatus.PENDING, PipelineStatus.QUEUED, PipelineStatus.RUNNING}:
            job.status = PipelineStatus.FAILED
            job.finished_at = finished_at
            job.logs.append(detail)
    _save_pipeline(pipeline, _payload_for_action(action), detail)


def recover_actions() -> int:
    """Requeue current queued Actions; safely finalize legacy pending/running rows."""
    with _db() as db:
        _ensure_schema(db)
        running = db.execute("SELECT id FROM native_action_runs WHERE status='running'").fetchall()
        queued_rows = db.execute(
            "SELECT id FROM native_action_runs WHERE status='queued'"
        ).fetchall()
        legacy_pending = db.execute(
            "SELECT id FROM native_action_runs WHERE status='pending'"
        ).fetchall()
        terminal = db.execute(
            """SELECT id FROM native_action_runs
               WHERE status IN ('success','failed','cancelled') AND action_ref IS NOT NULL"""
        ).fetchall()
    # A transient git failure after a terminal result must not retain the pinned
    # object indefinitely. This remains cleanup-only: no terminal Action runs again.
    for row in terminal:
        _cleanup_terminal_action_ref(row["id"])
    for row in running:
        action = _action_row(row["id"])
        if action is not None:
            _mark_interrupted(action, pipelines._get(row["id"]))
    for row in legacy_pending:
        action = _action_row(row["id"])
        if action is not None:
            _mark_unrecoverable_legacy_pending(action)
    queued = 0
    for row in queued_rows:
        action_id = row["id"]
        try:
            from amoscloud_ai.worker import run_native_action_task

            dispatch_task(run_native_action_task, action_id)
            queued += 1
        except Exception as exc:
            # A persisted request is not an actual queue hand-off. Fail it
            # visibly, rather than indefinitely presenting it as queued.
            action = _action_row(action_id)
            pipeline = pipelines._get(action_id)
            if action is not None and pipeline is not None:
                _mark_queue_unavailable(
                    action_id, pipeline, _payload_for_action(action), type(exc).__name__
                )
            elif action is not None:
                _update_action(
                    action_id,
                    status=PipelineStatus.FAILED,
                    finished_at=_now(),
                    error_detail=f"Worker queue unavailable: {type(exc).__name__}",
                )
                _cleanup_terminal_action_ref(action_id)
    return queued
