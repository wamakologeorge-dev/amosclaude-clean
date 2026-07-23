"""Authenticated, single-use website decisions for Amosclaud approval cards."""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import DB_PATH, get_user_from_session
from amoscloud_ai.api.routes.github_repositories import _connection, _db as github_db, _decrypt_token

router = APIRouter(prefix="/approvals", tags=["website-approvals"])

_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_APPROVAL_ID_RE = re.compile(r"^(?:issue:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+:\d+|run:\d+)$")
_ALLOWED_DECISIONS = {"approve", "deny"}
_ALLOWED_SOURCE_TYPES = {"approval", "workflow"}
_DEFAULT_WEBSITE_ORIGINS = {"https://wamakologeorge-dev.github.io"}
_COMMAND_REPOSITORY = os.getenv("AMOSCLAUD_COMMAND_REPOSITORY", "wamakologeorge-dev/Amosclaud1")


class ApprovalDecisionRequest(BaseModel):
    approval_id: str = Field(..., min_length=5, max_length=220)
    decision: str = Field(..., min_length=4, max_length=7)
    repository: str = Field(..., min_length=3, max_length=200)
    source_type: str = Field(..., min_length=3, max_length=20)
    evidence_url: str = Field(..., min_length=10, max_length=1000)
    single_use: bool


def _current_user(amos_session: str | None = Cookie(default=None)) -> sqlite3.Row:
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to Amosclaud before approving work")
    return user


def _allowed_origins() -> set[str]:
    configured = os.getenv("AMOSCLAUD_WEBSITE_ORIGINS", "")
    values = {item.strip().rstrip("/") for item in configured.split(",") if item.strip()}
    return values or set(_DEFAULT_WEBSITE_ORIGINS)


def _validate_origin(request: Request, decision_header: str | None) -> None:
    origin = (request.headers.get("origin") or "").rstrip("/")
    if origin not in _allowed_origins():
        raise HTTPException(status_code=403, detail="Website origin is not authorized")
    if decision_header != "website-v1":
        raise HTTPException(status_code=403, detail="Missing Amosclaud decision confirmation header")


def _decision_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS website_approval_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            approval_id TEXT NOT NULL UNIQUE,
            repository TEXT NOT NULL,
            source_type TEXT NOT NULL,
            evidence_url TEXT NOT NULL,
            decision TEXT NOT NULL CHECK(decision IN ('approve','deny')),
            user_id INTEGER NOT NULL,
            github_login TEXT NOT NULL,
            github_record_url TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    db.commit()
    return db


async def _github_request(
    client: httpx.AsyncClient,
    token: str,
    method: str,
    path: str,
    payload: dict | None = None,
) -> dict:
    response = await client.request(
        method,
        f"https://api.github.com{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json=payload,
    )
    if response.status_code >= 400:
        detail = "GitHub rejected the approval action"
        try:
            detail = str(response.json().get("message") or detail)
        except ValueError:
            pass
        raise HTTPException(status_code=502, detail=detail)
    try:
        result = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="GitHub returned an invalid response") from exc
    return result if isinstance(result, dict) else {"items": result}


async def _authorized_connection(user: sqlite3.Row, repository: str) -> tuple[str, str]:
    with github_db() as db:
        connection = _connection(db, int(user["id"]))
        token = _decrypt_token(str(connection["access_token_ciphertext"]))
        github_login = str(connection["github_login"])

    async with httpx.AsyncClient(timeout=20) as client:
        repo = await _github_request(client, token, "GET", f"/repos/{repository}")
    permissions = repo.get("permissions") or {}
    may_write = any(bool(permissions.get(name)) for name in ("admin", "maintain", "push"))
    if not may_write:
        raise HTTPException(status_code=403, detail="Your connected GitHub account cannot approve changes in this repository")
    return token, github_login


def _validate_payload(body: ApprovalDecisionRequest) -> None:
    body.decision = body.decision.strip().lower()
    body.source_type = body.source_type.strip().lower()
    if body.decision not in _ALLOWED_DECISIONS:
        raise HTTPException(status_code=422, detail="Decision must be approve or deny")
    if body.source_type not in _ALLOWED_SOURCE_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported approval source")
    if not body.single_use:
        raise HTTPException(status_code=422, detail="Website approvals must be single-use")
    if not _REPOSITORY_RE.fullmatch(body.repository):
        raise HTTPException(status_code=422, detail="Invalid repository")
    if not _APPROVAL_ID_RE.fullmatch(body.approval_id):
        raise HTTPException(status_code=422, detail="Invalid approval identifier")
    evidence = urlparse(body.evidence_url)
    if evidence.scheme != "https" or evidence.hostname not in {"github.com", "www.github.com"}:
        raise HTTPException(status_code=422, detail="Evidence must be a GitHub HTTPS URL")


def _issue_number(body: ApprovalDecisionRequest) -> int:
    prefix = f"issue:{body.repository}:"
    if not body.approval_id.startswith(prefix):
        raise HTTPException(status_code=422, detail="Approval issue does not match the repository")
    return int(body.approval_id.removeprefix(prefix))


async def _record_on_github(token: str, body: ApprovalDecisionRequest) -> str:
    async with httpx.AsyncClient(timeout=20) as client:
        if body.source_type == "approval":
            number = _issue_number(body)
            issue = await _github_request(client, token, "GET", f"/repos/{body.repository}/issues/{number}")
            title = str(issue.get("title") or "")
            if not title.startswith("[Amosclaud Approval Required]"):
                raise HTTPException(status_code=409, detail="The source issue is not an Amosclaud approval request")
            comment = await _github_request(
                client,
                token,
                "POST",
                f"/repos/{body.repository}/issues/{number}/comments",
                {"body": f"@amosclaud {body.decision}"},
            )
            return str(comment.get("html_url") or body.evidence_url)

        if body.decision == "deny":
            return body.evidence_url

        command_issue = await _github_request(
            client,
            token,
            "POST",
            f"/repos/{_COMMAND_REPOSITORY}/issues",
            {
                "title": f"Website-approved inspection for {body.repository}",
                "body": (
                    "## Amosclaud website approval\n\n"
                    f"**Target repository:** `{body.repository}`\n"
                    f"**Failed-run evidence:** {body.evidence_url}\n"
                    f"**Approval ID:** `{body.approval_id}`\n"
                    "**Scope:** Inspect the failed workflow and prepare a verified repair plan. "
                    "Do not publish repository changes without any additional approval required by policy."
                ),
            },
        )
        number = int(command_issue["number"])
        await _github_request(
            client,
            token,
            "POST",
            f"/repos/{_COMMAND_REPOSITORY}/issues/{number}/comments",
            {
                "body": (
                    "@amosclaud inspect the failed workflow evidence and prepare a verified repair plan "
                    f"for {body.repository}: {body.evidence_url}"
                )
            },
        )
        return str(command_issue.get("html_url") or body.evidence_url)


@router.post("/decision")
async def decide_approval(
    body: ApprovalDecisionRequest,
    request: Request,
    user: sqlite3.Row = Depends(_current_user),
    x_amosclaud_decision: str | None = Header(default=None),
) -> dict:
    _validate_origin(request, x_amosclaud_decision)
    _validate_payload(body)

    with _decision_db() as db:
        existing = db.execute(
            "SELECT decision,github_record_url,created_at FROM website_approval_decisions WHERE approval_id=?",
            (body.approval_id,),
        ).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="This single-use approval has already been decided")

    token, github_login = await _authorized_connection(user, body.repository)
    github_record_url = await _record_on_github(token, body)
    created_at = datetime.now(timezone.utc).isoformat()

    try:
        with _decision_db() as db:
            db.execute(
                """INSERT INTO website_approval_decisions(
                    approval_id,repository,source_type,evidence_url,decision,user_id,github_login,github_record_url,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    body.approval_id,
                    body.repository,
                    body.source_type,
                    body.evidence_url,
                    body.decision,
                    int(user["id"]),
                    github_login,
                    github_record_url,
                    created_at,
                ),
            )
            db.commit()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="This single-use approval has already been decided") from exc

    return {
        "recorded": True,
        "approval_id": body.approval_id,
        "decision": body.decision,
        "repository": body.repository,
        "single_use": True,
        "github_login": github_login,
        "github_record_url": github_record_url,
        "recorded_at": created_at,
    }
