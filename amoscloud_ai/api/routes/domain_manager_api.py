"""Authenticated Amosclaud Domain Manager API."""

from __future__ import annotations

import json
import os
from datetime import datetime

from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import _connect, get_user_from_session
from amoscloud_ai.domain_manager import (
    DomainManagerError,
    DomainVerification,
    VercelDomainManager,
)

router = APIRouter(prefix="/domains", tags=["amosclaud-domain-manager"])


class DomainVerificationRequest(BaseModel):
    domain: str = Field(min_length=3, max_length=253)
    project: str | None = Field(default=None, max_length=160)
    team_id: str | None = Field(default=None, max_length=160)


def _user(token: str | None):
    user = get_user_from_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to use Amosclaud Domain Manager")
    return user


def _ensure_schema() -> None:
    with _connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS domain_verification_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                domain TEXT NOT NULL,
                provider TEXT NOT NULL,
                project TEXT NOT NULL,
                team_id TEXT,
                status TEXT NOT NULL,
                verified INTEGER NOT NULL DEFAULT 0,
                checked_at TEXT NOT NULL,
                record_json TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        db.execute(
            """CREATE INDEX IF NOT EXISTS idx_domain_verification_latest
               ON domain_verification_records(user_id, domain, checked_at DESC)"""
        )
        db.commit()


def _save(user_id: int, record: DomainVerification) -> int:
    _ensure_schema()
    with _connect() as db:
        cursor = db.execute(
            """INSERT INTO domain_verification_records(
                   user_id,domain,provider,project,team_id,status,verified,checked_at,record_json
               ) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                user_id,
                record.domain,
                record.provider_expected,
                record.project,
                record.team_id,
                record.status,
                1 if record.verified else 0,
                record.checked_at.isoformat(),
                record.model_dump_json(),
            ),
        )
        db.commit()
        return int(cursor.lastrowid)


def _default_project() -> str:
    return (
        os.getenv("VERCEL_PROJECT_ID", "").strip()
        or os.getenv("VERCEL_PROJECT_NAME", "").strip()
    )


@router.post("/verify")
async def verify_domain(
    body: DomainVerificationRequest,
    amos_session: str | None = Cookie(default=None),
) -> dict:
    """Run the complete Vercel + DNS + HTTPS proof chain and persist its evidence."""

    user = _user(amos_session)
    project = (body.project or _default_project()).strip()
    if not project:
        raise HTTPException(
            status_code=503,
            detail="Set VERCEL_PROJECT_ID/VERCEL_PROJECT_NAME or provide project",
        )
    team_id = body.team_id or os.getenv("VERCEL_TEAM_ID", "").strip() or None
    try:
        record = await VercelDomainManager().verify(
            domain=body.domain,
            project=project,
            team_id=team_id,
        )
    except DomainManagerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    record_id = _save(int(user["id"]), record)
    return {
        "record_id": record_id,
        "truth": record.model_dump(mode="json"),
    }


@router.get("/{domain}/verification")
def latest_verification(
    domain: str,
    amos_session: str | None = Cookie(default=None),
) -> dict:
    """Return the latest saved Amosclaud verification record for this user/domain."""

    user = _user(amos_session)
    try:
        normalized = VercelDomainManager.normalize_domain(domain)
    except DomainManagerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _ensure_schema()
    with _connect() as db:
        row = db.execute(
            """SELECT id,record_json FROM domain_verification_records
               WHERE user_id=? AND domain=? ORDER BY checked_at DESC,id DESC LIMIT 1""",
            (int(user["id"]), normalized),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No Amosclaud verification record found")
    return {
        "record_id": int(row["id"]),
        "truth": json.loads(row["record_json"]),
    }


@router.get("/verification/history")
def verification_history(
    amos_session: str | None = Cookie(default=None),
) -> list[dict]:
    """Return recent evidence records without exposing the Vercel access token."""

    user = _user(amos_session)
    _ensure_schema()
    with _connect() as db:
        rows = db.execute(
            """SELECT id,domain,provider,project,team_id,status,verified,checked_at
               FROM domain_verification_records
               WHERE user_id=? ORDER BY checked_at DESC,id DESC LIMIT 100""",
            (int(user["id"]),),
        ).fetchall()
    return [
        {
            "record_id": int(row["id"]),
            "domain": row["domain"],
            "provider": row["provider"],
            "project": row["project"],
            "team_id": row["team_id"],
            "status": row["status"],
            "verified": bool(row["verified"]),
            "checked_at": datetime.fromisoformat(row["checked_at"]).isoformat(),
        }
        for row in rows
    ]
