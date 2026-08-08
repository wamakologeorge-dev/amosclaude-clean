"""Self-service Amosclaud account controls."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import (
    DB_PATH,
    SESSION_COOKIE,
    SESSION_DAYS,
    _connect,
    _cookie_secure,
    _create_session,
    _token_hash,
    _verify_password,
    get_user_from_session,
)
from amoscloud_ai.api.routes.repositories import REPOSITORY_ROOT
from amoscloud_ai.api.routes.storage import STORAGE_ROOT

router = APIRouter(prefix="/account", tags=["account"])


def _configured_domains() -> list[str]:
    """Read the domains this deployment is configured to serve."""
    raw = os.getenv("ALLOWED_HOSTS", "").strip()
    hosts: list[str] = []
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                hosts = [str(item).strip() for item in parsed]
        except (ValueError, TypeError):
            hosts = [part.strip() for part in raw.split(",")]
    public_url = os.getenv("AMOSCLAUD_PUBLIC_URL", "").strip()
    if public_url:
        host = public_url.split("://", 1)[-1].split("/", 1)[0]
        if host:
            hosts.append(host)
    seen: set[str] = set()
    ordered: list[str] = []
    for host in hosts:
        host = host.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].strip().lower()
        if host and host not in ("*", "localhost", "127.0.0.1", "testserver") and host not in seen:
            seen.add(host)
            ordered.append(host)
    return ordered


def _is_admin(user) -> bool:
    """Read is_admin from either a dict or a sqlite3.Row session user."""
    try:
        return bool(user["is_admin"])
    except (KeyError, IndexError, TypeError):
        return False


def _positive_limit(name: str, default: int) -> int:
    """Read one bounded positive per-user limit from the environment."""
    try:
        value = int(os.getenv(name, str(default)).strip())
    except (AttributeError, ValueError):
        value = default
    return max(1, min(value, 100_000))


def _table_exists(db: sqlite3.Connection, name: str) -> bool:
    return (
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        is not None
    )


def _account_usage(db: sqlite3.Connection, user_id: int) -> dict[str, int]:
    """Return counts belonging only to the selected Amosclaud account."""
    owned_repositories = 0
    shared_repositories = 0
    active_api_keys = 0
    if _table_exists(db, "repositories"):
        owned_repositories = int(
            db.execute(
                "SELECT COUNT(*) FROM repositories WHERE owner_id=?",
                (user_id,),
            ).fetchone()[0]
        )
    if _table_exists(db, "repository_collaborators"):
        shared_repositories = int(
            db.execute(
                "SELECT COUNT(*) FROM repository_collaborators WHERE user_id=?",
                (user_id,),
            ).fetchone()[0]
        )
    if _table_exists(db, "autonomous_api_keys"):
        active_api_keys = int(
            db.execute(
                "SELECT COUNT(*) FROM autonomous_api_keys "
                "WHERE user_id=? AND revoked_at IS NULL",
                (user_id,),
            ).fetchone()[0]
        )
    return {
        "owned_repositories": owned_repositories,
        "shared_repositories": shared_repositories,
        "active_api_keys": active_api_keys,
    }


def _cookie_domain() -> str | None:
    """Return the optional shared cookie domain configured by the operator."""
    value = os.getenv("AUTH_COOKIE_DOMAIN", "").strip()
    return value or None


def _clear_session_cookie(response: Response) -> None:
    """Clear current and legacy host-only session cookies."""
    domain = _cookie_domain()
    if domain:
        response.delete_cookie(SESSION_COOKIE, path="/", domain=domain)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/settings")
def account_settings(amos_session: str | None = Cookie(default=None)) -> dict:
    """Report which account tools are available on this deployment."""
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    billing_ready = bool(os.getenv("STRIPE_SECRET_KEY"))
    github_ready = bool(os.getenv("GITHUB_CLIENT_ID") and os.getenv("GITHUB_CLIENT_SECRET"))
    administrator = _is_admin(user)
    return {
        "profile": {"available": True},
        "github_connection": {
            "available": github_ready,
            "href": "/api/v1/github/connect",
        },
        "api_keys": {
            "available": True,
            "admin_only": False,
            "href": "/account#api-keys",
            "api_path": "/api/v1/agent/keys",
        },
        "service_keys": {
            "available": administrator,
            "admin_only": True,
            "href": "/admin/service-keys",
        },
        "billing": {"available": billing_ready, "href": "/plans"},
        "domain_verification": {
            "available": bool(_configured_domains()),
            "href": "/api/v1/account/domains",
        },
        "multi_user": {
            "enabled": True,
            "shared_platform_service": True,
            "account_isolation": "per-user",
        },
        "is_admin": administrator,
    }


@router.get("/overview")
def account_overview(amos_session: str | None = Cookie(default=None)) -> dict[str, object]:
    """Return the signed-in user's isolated plan, usage, and platform identity."""
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    from amoscloud_ai.api.routes.billing import _entitlement
    from amoscloud_ai.organization_support import support_wallet

    user_id = int(user["id"])
    administrator = _is_admin(user)
    with _connect() as db:
        plan = _entitlement(db, user_id)
        usage = _account_usage(db, user_id)
        wallet = support_wallet(db, user_id)

    return {
        "account": {
            "id": user_id,
            "name": str(user["name"]),
            "email": str(user["email"]),
            "is_admin": administrator,
            "provider": str(user["provider"]),
        },
        "platform": {
            "name": "Amosclaud",
            "deployment_model": "single-service",
            "multi_user": True,
            "account_isolation": "per-user",
        },
        "plan": plan,
        "usage": {
            **usage,
            "hosted_tool_seconds_remaining": (
                None if administrator else wallet["remaining_seconds"]
            ),
            "hosted_tool_lifetime_seconds": (None if administrator else wallet["lifetime_seconds"]),
        },
        "limits": {
            "repositories": (
                None if administrator else _positive_limit("MAX_REPOSITORIES_PER_USER", 10)
            ),
            "autonomous_api_keys": (
                None if administrator else _positive_limit("MAX_AUTONOMOUS_KEYS_PER_USER", 10)
            ),
            "administrator_bypass": administrator,
        },
        "routes": {
            "api_keys": "/api/v1/agent/keys",
            "billing": "/api/v1/billing/status",
            "support_time": "/api/v1/support-time/status",
            "repositories": "/api/v1/repositories",
        },
    }


@router.get("/domains")
def account_domains(
    request: Request,
    amos_session: str | None = Cookie(default=None),
) -> dict:
    """Domain verification status for this deployment."""
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    current_host = (request.headers.get("host") or request.url.netloc or "").split(":", 1)[0]
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    domains = [
        {
            "domain": host,
            "active": host == current_host,
            "https": forwarded_proto == "https",
        }
        for host in _configured_domains()
    ]
    return {"domains": domains, "current_host": current_host}


@router.post("/share-session", status_code=204, response_class=Response)
def share_session_across_domains(
    response: Response,
    amos_session: str | None = Cookie(default=None),
) -> Response:
    """Rotate and reissue a verified session for the configured parent domain."""
    user = get_user_from_session(amos_session)
    if not user or not amos_session:
        raise HTTPException(status_code=401, detail="Not authenticated")

    with _connect() as db:
        shared_token = _create_session(db, int(user["id"]))
        db.execute(
            "DELETE FROM sessions WHERE token_hash=?",
            (_token_hash(amos_session),),
        )
        db.commit()

    domain = _cookie_domain()
    if domain:
        response.delete_cookie(SESSION_COOKIE, path="/")
    response.set_cookie(
        SESSION_COOKIE,
        shared_token,
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
        domain=domain,
    )
    response.status_code = 204
    return response


@router.post("/logout-all", status_code=204, response_class=Response)
def logout_all_devices(
    response: Response,
    amos_session: str | None = Cookie(default=None),
) -> Response:
    """Revoke every active session belonging to the signed-in user."""
    user = get_user_from_session(amos_session)
    if not user:
        _clear_session_cookie(response)
        response.status_code = 204
        return response
    with _connect() as db:
        db.execute("DELETE FROM sessions WHERE user_id=?", (int(user["id"]),))
        db.commit()
    _clear_session_cookie(response)
    response.status_code = 204
    return response


class AccountDeleteRequest(BaseModel):
    confirmation: str = Field(..., min_length=6, max_length=254)
    password: str | None = Field(default=None, max_length=200)


def _owned_repository_ids(db: sqlite3.Connection, user_id: int) -> list[int]:
    table = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='repositories'"
    ).fetchone()
    if not table:
        return []
    return [
        int(row[0])
        for row in db.execute("SELECT id FROM repositories WHERE owner_id=?", (user_id,)).fetchall()
    ]


def _delete_foreign_key_rows(db: sqlite3.Connection, user_id: int) -> None:
    tables = [
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master " "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
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
        raise HTTPException(
            status_code=400,
            detail="Enter your account email exactly to confirm deletion",
        )

    repository_ids: list[int] = []
    with _connect() as db:
        full_user = db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
        if not full_user:
            raise HTTPException(status_code=404, detail="Account not found")
        if full_user["password_hash"]:
            if not body.password or not _verify_password(body.password, full_user["password_hash"]):
                raise HTTPException(
                    status_code=401,
                    detail="Password confirmation is required",
                )

        repository_ids = _owned_repository_ids(db, int(user["id"]))
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM auth_codes WHERE email=?", (expected,))
            _delete_foreign_key_rows(db, int(user["id"]))
            db.execute("DELETE FROM users WHERE id=?", (int(user["id"]),))
            db.commit()
        except sqlite3.DatabaseError as exc:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Account data could not be removed safely",
            ) from exc

    for repository_id in repository_ids:
        shutil.rmtree(REPOSITORY_ROOT / str(repository_id), ignore_errors=True)
    shutil.rmtree(STORAGE_ROOT / "user" / str(user["id"]), ignore_errors=True)
    shutil.rmtree(STORAGE_ROOT / "admin" / str(user["id"]), ignore_errors=True)

    _clear_session_cookie(response)
    response.status_code = 204
    return response
