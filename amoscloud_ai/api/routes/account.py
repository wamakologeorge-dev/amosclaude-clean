"""Self-service Amosclaud account controls."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Cookie, HTTPException, Response
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import (
    DB_PATH,
    SESSION_COOKIE,
    _connect,
    _verify_password,
    get_user_from_session,
)
from amoscloud_ai.api.routes.repositories import REPOSITORY_ROOT
from amoscloud_ai.api.routes.storage import STORAGE_ROOT

router = APIRouter(prefix="/account", tags=["account"])


class AccountDeleteRequest(BaseModel):
    confirmation: str = Field(..., min_length=6, max_length=254)
    password: str | None = Field(default=None, max_length=200)


def _owned_repository_ids(db: sqlite3.Connection, user_id: int) -> list[int]:
    table = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='repositories'"
    ).fetchone()
    if not table:
        return []
    return [int(row[0]) for row in db.execute("SELECT id FROM repositories WHERE owner_id=?", (user_id,)).fetchall()]


def _delete_foreign_key_rows(db: sqlite3.Connection, user_id: int) -> None:
    tables = [
        row[0]
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
        if row[0] != "users"
    ]
    for table in tables:
        foreign_keys = db.execute(f'PRAGMA foreign_key_list("{table}")').fetchall()
        user_columns = [row[3] for row in foreign_keys if row[2] == "users" and row[4] == "id"]
        for column in user_columns:
            db.execute(f'DELETE FROM "{table}" WHERE "{column}"=?', (user_id,))


@router.delete("", status_code=204)
def delete_account(
    body: AccountDeleteRequest,
    response: Response,
    amos_session: str | None = Cookie(default=None),
) -> Response:
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    expected = user["email"].strip().lower()
    if body.confirmation.strip().lower() != expected:
        raise HTTPException(status_code=400, detail="Enter your account email exactly to confirm deletion")

    repository_ids: list[int] = []
    with _connect() as db:
        full_user = db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
        if not full_user:
            raise HTTPException(status_code=404, detail="Account not found")
        if full_user["password_hash"]:
            if not body.password or not _verify_password(body.password, full_user["password_hash"]):
                raise HTTPException(status_code=401, detail="Password confirmation is required")

        repository_ids = _owned_repository_ids(db, int(user["id"]))
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM auth_codes WHERE email=?", (expected,))
            _delete_foreign_key_rows(db, int(user["id"]))
            db.execute("DELETE FROM users WHERE id=?", (int(user["id"]),))
            db.commit()
        except sqlite3.DatabaseError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="Account data could not be removed safely") from exc

    for repository_id in repository_ids:
        shutil.rmtree(REPOSITORY_ROOT / str(repository_id), ignore_errors=True)
    shutil.rmtree(STORAGE_ROOT / "user" / str(user["id"]), ignore_errors=True)
    shutil.rmtree(STORAGE_ROOT / "admin" / str(user["id"]), ignore_errors=True)

    response.delete_cookie(SESSION_COOKIE, path="/")
    response.status_code = 204
    return response
