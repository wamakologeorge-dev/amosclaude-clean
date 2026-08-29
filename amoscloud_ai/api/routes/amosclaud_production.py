"""Amosclaud-first production, CI, and native pull-request controls."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai import first_production
from amoscloud_ai.api.routes import pipelines, solo_development
from amoscloud_ai.api.routes.repositories import (
    _access,
    _checkout,
    _current_user,
    _db,
    _open,
    _repo_lock,
    _require_write,
    _safe_branch,
)
from amoscloud_ai.models import PipelineTrigger

router = APIRouter(prefix="/amosclaud/production", tags=["amosclaud-production"])


class CIRunRequest(BaseModel):
    branch: str = Field(default="main", min_length=1, max_length=200)
    commit_sha: str | None = Field(default=None, max_length=80)
    reason: str = Field(default="Amosclaud CI", max_length=500)


class PullRequestAction(BaseModel):
    action: Literal["close", "reopen", "delete", "restore", "merge", "unmerge"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_control_tables(db: sqlite3.Connection) -> None:
    solo_development._ensure_tables(db)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS amosclaud_pr_controls (
            repository_id INTEGER NOT NULL,
            pull_request_id INTEGER NOT NULL,
            deleted_at TEXT,
            restored_at TEXT,
            reverted_commit TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(repository_id, pull_request_id)
        );
        """)
    db.commit()


def _latest_ci(repository_id: int, branch: str) -> dict[str, Any] | None:
    with pipelines._db() as db:
        rows = db.execute(
            "SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT 200"
        ).fetchall()
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            continue
        nested = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        tagged_repository = payload.get("repository_id", nested.get("repository_id"))
        authoritative = payload.get("authoritative", nested.get("authoritative", False))
        if str(tagged_repository) != str(repository_id) or not authoritative:
            continue
        if str(row["branch"]) != branch:
            continue
        return {
            "id": row["id"],
            "status": row["status"],
            "branch": row["branch"],
            "commit_sha": payload.get("commit_sha") or nested.get("commit_sha"),
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "message": row["message"],
            "error_detail": row["error_detail"],
        }
    return None


def _pull_request(db: sqlite3.Connection, repository_id: int, pull_request_id: int) -> sqlite3.Row:
    _ensure_control_tables(db)
    row = db.execute(
        "SELECT * FROM native_pull_requests WHERE id=? AND repository_id=?",
        (pull_request_id, repository_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Pull request not found")
    return row


def _control(db: sqlite3.Connection, repository_id: int, pull_request_id: int) -> dict[str, Any]:
    row = db.execute(
        "SELECT * FROM amosclaud_pr_controls WHERE repository_id=? AND pull_request_id=?",
        (repository_id, pull_request_id),
    ).fetchone()
    return (
        dict(row)
        if row
        else {
            "repository_id": repository_id,
            "pull_request_id": pull_request_id,
            "deleted_at": None,
            "restored_at": None,
            "reverted_commit": None,
            "updated_at": None,
        }
    )


def _write_control(
    db: sqlite3.Connection,
    repository_id: int,
    pull_request_id: int,
    *,
    deleted_at: str | None = None,
    restored_at: str | None = None,
    reverted_commit: str | None = None,
) -> None:
    current = _control(db, repository_id, pull_request_id)
    db.execute(
        """INSERT INTO amosclaud_pr_controls(
               repository_id,pull_request_id,deleted_at,restored_at,reverted_commit,updated_at
           ) VALUES (?,?,?,?,?,?)
           ON CONFLICT(repository_id,pull_request_id) DO UPDATE SET
               deleted_at=excluded.deleted_at,
               restored_at=excluded.restored_at,
               reverted_commit=excluded.reverted_commit,
               updated_at=excluded.updated_at""",
        (
            repository_id,
            pull_request_id,
            deleted_at if deleted_at is not None else current["deleted_at"],
            restored_at if restored_at is not None else current["restored_at"],
            reverted_commit if reverted_commit is not None else current["reverted_commit"],
            _now(),
        ),
    )
    db.commit()


@router.get("/manifest")
def production_manifest() -> dict[str, Any]:
    return first_production.manifest()


@router.get("/repositories/{repository_id}/status")
def repository_production_status(
    repository_id: int,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    with _db() as db:
        _ensure_control_tables(db)
        access = _access(db, repository_id, int(user["id"]))
        repo = _open(repository_id)
        default_branch = str(access["default_branch"] or "main")
        head_sha = repo.commit(default_branch).hexsha
        issues = db.execute(
            "SELECT COUNT(*) AS count FROM native_issues WHERE repository_id=? AND state='open'",
            (repository_id,),
        ).fetchone()["count"]
        pull_requests = db.execute(
            "SELECT COUNT(*) AS count FROM native_pull_requests WHERE repository_id=? AND state='open'",
            (repository_id,),
        ).fetchone()["count"]

    ci = _latest_ci(repository_id, default_branch)
    truth = first_production.production_truth(
        ci_status=ci["status"] if ci else None,
        head_sha=head_sha,
        verified_sha=ci["commit_sha"] if ci else None,
    )
    return {
        **truth,
        "repository_id": repository_id,
        "branch": default_branch,
        "head_sha": head_sha,
        "open_issues": int(issues),
        "open_pull_requests": int(pull_requests),
        "latest_ci": ci,
    }


@router.post("/repositories/{repository_id}/ci", status_code=201)
async def run_amosclaud_ci(
    repository_id: int,
    body: CIRunRequest,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    branch = _safe_branch(body.branch)
    with _repo_lock(repository_id), _db() as db:
        access = _access(db, repository_id, int(user["id"]))
        _require_write(access)
        repo = _open(repository_id)
        if branch not in {item.name for item in repo.heads}:
            raise HTTPException(status_code=404, detail="CI branch not found")
        head_sha = repo.commit(branch).hexsha
        if body.commit_sha and body.commit_sha != head_sha:
            raise HTTPException(status_code=409, detail="Requested CI revision is stale")

    result = await pipelines.trigger_pipeline(
        PipelineTrigger(
            trigger="amosclaud-ci",
            branch=branch,
            commit_sha=head_sha,
            payload={
                "repository_id": repository_id,
                "authoritative": True,
                "commit_sha": head_sha,
                "requested_by": int(user["id"]),
                "reason": body.reason,
            },
        )
    )
    return {
        "authority": "amosclaud",
        "pipeline": result.model_dump(mode="json"),
        "color": first_production.ci_color(result.status.value),
        "commit_sha": head_sha,
    }


@router.get("/repositories/{repository_id}/pull-requests")
def production_pull_requests(
    repository_id: int,
    user: sqlite3.Row = Depends(_current_user),
) -> list[dict[str, Any]]:
    with _db() as db:
        _ensure_control_tables(db)
        _access(db, repository_id, int(user["id"]))
        rows = db.execute(
            "SELECT * FROM native_pull_requests WHERE repository_id=? ORDER BY id DESC",
            (repository_id,),
        ).fetchall()
        result = []
        for row in rows:
            control = _control(db, repository_id, int(row["id"]))
            if control["deleted_at"] and not control["restored_at"]:
                continue
            item = solo_development._pr_dict(row)
            item["control"] = control
            result.append(item)
        return result


@router.get("/repositories/{repository_id}/pull-requests/{pull_request_id}/ci")
def pull_request_ci_status(
    repository_id: int,
    pull_request_id: int,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    """Return the latest authoritative Amosclaud Action for one native PR."""
    with _db() as db:
        _access(db, repository_id, int(user["id"]))
        row = _pull_request(db, repository_id, pull_request_id)
        branch = str(row["head_branch"])
    repo = _open(repository_id)
    head_sha = repo.commit(branch).hexsha
    return {
        "authority": "amosclaud",
        "pull_request_id": pull_request_id,
        "branch": branch,
        "commit_sha": head_sha,
        "pipeline": _latest_ci(repository_id, branch),
    }


@router.post("/repositories/{repository_id}/pull-requests/{pull_request_id}/ci", status_code=201)
async def run_pull_request_ci(
    repository_id: int,
    pull_request_id: int,
    body: CIRunRequest,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    """Run Amosclaud's authoritative checks for this PR's exact head branch."""
    with _db() as db:
        _access(db, repository_id, int(user["id"]))
        row = _pull_request(db, repository_id, pull_request_id)
        branch = str(row["head_branch"])
    return await run_amosclaud_ci(
        repository_id,
        CIRunRequest(
            branch=branch,
            commit_sha=body.commit_sha,
            reason=body.reason or f"Amosclaud Action for pull request #{pull_request_id}",
        ),
        user,
    )


@router.post("/repositories/{repository_id}/pull-requests/{pull_request_id}/action")
def control_pull_request(
    repository_id: int,
    pull_request_id: int,
    body: PullRequestAction,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    with _repo_lock(repository_id), _db() as db:
        _ensure_control_tables(db)
        access = _access(db, repository_id, int(user["id"]))
        _require_write(access)
        row = _pull_request(db, repository_id, pull_request_id)
        action = body.action

        if action == "close":
            if row["state"] != "open":
                raise HTTPException(
                    status_code=409, detail="Only an open pull request can be closed"
                )
            db.execute(
                "UPDATE native_pull_requests SET state='closed',updated_at=? WHERE id=?",
                (_now(), pull_request_id),
            )
            db.commit()
        elif action == "reopen":
            if row["state"] != "closed":
                raise HTTPException(
                    status_code=409, detail="Only a closed pull request can be reopened"
                )
            db.execute(
                "UPDATE native_pull_requests SET state='open',updated_at=? WHERE id=?",
                (_now(), pull_request_id),
            )
            db.commit()
        elif action == "delete":
            _write_control(db, repository_id, pull_request_id, deleted_at=_now(), restored_at="")
        elif action == "restore":
            current = _control(db, repository_id, pull_request_id)
            if not current["deleted_at"]:
                raise HTTPException(status_code=409, detail="Pull request is not deleted")
            _write_control(db, repository_id, pull_request_id, deleted_at="", restored_at=_now())
        elif action == "merge":
            if row["state"] != "open":
                raise HTTPException(status_code=409, detail="Pull request is not open")
            repo = _open(repository_id)
            head_sha = repo.commit(row["head_branch"]).hexsha
            ci = _latest_ci(repository_id, row["head_branch"])
            if not first_production.merge_allowed(
                ci_status=ci["status"] if ci else None,
                head_sha=head_sha,
                verified_sha=ci["commit_sha"] if ci else None,
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Amosclaud CI must be green for the exact pull-request head before merge",
                )
            return solo_development.merge_pull_request(repository_id, pull_request_id, user)
        elif action == "unmerge":
            if row["state"] != "merged" or not row["merge_commit"]:
                raise HTTPException(
                    status_code=409, detail="Only a merged pull request can be unmerged"
                )
            repo = _open(repository_id)
            _checkout(repo, row["base_branch"])
            try:
                repo.git.revert("-m", "1", row["merge_commit"], "--no-edit")
            except Exception as exc:
                try:
                    repo.git.revert("--abort")
                except Exception as abort_exc:
                    raise HTTPException(
                        status_code=500,
                        detail="Unmerge failed and repository cleanup could not complete",
                    ) from abort_exc
                raise HTTPException(status_code=409, detail="Unmerge revert failed") from exc
            reverted = repo.head.commit.hexsha
            _write_control(db, repository_id, pull_request_id, reverted_commit=reverted)

        refreshed = _pull_request(db, repository_id, pull_request_id)
        return {
            "pull_request": solo_development._pr_dict(refreshed),
            "control": _control(db, repository_id, pull_request_id),
            "action": action,
        }


__all__ = ["router"]
