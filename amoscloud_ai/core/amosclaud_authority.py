"""Shared Amosclaud identity and workspace-grant authority.

The authority is deliberately independent from GitHub Actions and Ollama. It
issues first-party credentials for Amosclaud products and separately records
short-lived, workspace-admin-authorized credentials for external providers.

Only hashes are persisted. First-party credentials are manually revocable and
do not receive an automatic expiration date. External grants must carry an
expiration and are rejected when the requested lifetime is shorter than the
platform's 90-day minimum.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from amoscloud_ai.api.routes import auth

PLATFORM_CREDENTIAL_KINDS = frozenset({"api_key", "token", "action"})
PLATFORM_SCOPES = frozenset(
    {
        "answer",
        "inspect",
        "plan",
        "build",
        "fix",
        "test",
        "deploy",
        "monitor",
        "workspace:read",
        "workspace:write",
        "repository:read",
        "repository:write",
        "tasks:read",
        "tasks:write",
        "github:read",
        "github:write",
        "ci:read",
        "ci:run",
        "pull-requests:read",
        "pull-requests:create",
        "pull-requests:update",
        "jobs:read",
        "jobs:update",
        "deployments:read",
        "deployments:run",
        "model:invoke",
        "action:run",
        "authority:admin",
    }
)
THIRD_PARTY_SCOPES = PLATFORM_SCOPES - {"authority:admin"}
MIN_THIRD_PARTY_GRANT_DAYS = 90
MAX_THIRD_PARTY_GRANT_DAYS = 3650
_WORKSPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_PROVIDER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

_PREFIXES = {
    "api_key": "amos_api_",
    "token": "amos_token_",
    "action": "amos_action_",
}


class AuthorityError(ValueError):
    """Base class for safe, user-facing authority validation errors."""


class ScopeError(AuthorityError):
    """Raised when a credential requests an unknown or disallowed scope."""


class CredentialNotFound(AuthorityError):
    """Raised when a credential does not exist or is not active."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _new_secret(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(36)


def _normalise_name(value: str) -> str:
    name = " ".join(str(value or "").split())
    if not 2 <= len(name) <= 100:
        raise AuthorityError("Credential name must contain between 2 and 100 characters")
    return name


def _normalise_scopes(scopes: Iterable[str], *, allowed: set[str] | frozenset[str]) -> list[str]:
    values = {str(scope).strip() for scope in scopes if str(scope).strip()}
    if not values:
        raise ScopeError("At least one scope is required")
    unknown = sorted(values - allowed)
    if unknown:
        raise ScopeError(f"Unsupported scope(s): {', '.join(unknown)}")
    return sorted(values)


def _normalise_workspace_id(value: str) -> str:
    workspace_id = str(value or "").strip()
    if not _WORKSPACE_RE.fullmatch(workspace_id):
        raise AuthorityError("Invalid workspace identifier")
    return workspace_id


def _normalise_provider(value: str) -> str:
    provider = str(value or "").strip().lower()
    if not _PROVIDER_RE.fullmatch(provider):
        raise AuthorityError(
            "Provider must use lowercase letters, numbers, dots, hyphens, or underscores"
        )
    return provider


def _normalise_subject(value: str) -> str:
    subject = " ".join(str(value or "").split())
    if not 1 <= len(subject) <= 254:
        raise AuthorityError("Third-party subject must contain between 1 and 254 characters")
    return subject


def _loads_scopes(value: str | None) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return sorted({str(item) for item in parsed if str(item).strip()})


def _expires_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _active(row: sqlite3.Row, now: datetime | None = None) -> bool:
    if row["revoked_at"]:
        return False
    expiry = _expires_at(row["expires_at"])
    return expiry is None or expiry > (now or _now())


def _record_event(
    db: sqlite3.Connection,
    *,
    principal_type: str,
    principal_id: int,
    actor_user_id: int | None,
    event: str,
    details: dict[str, Any] | None = None,
) -> None:
    db.execute(
        """INSERT INTO amosclaud_authority_events(
               principal_type,principal_id,actor_user_id,event,details_json,created_at
           ) VALUES (?,?,?,?,?,?)""",
        (
            principal_type,
            principal_id,
            actor_user_id,
            event,
            json.dumps(details or {}, sort_keys=True, separators=(",", ":")),
            _iso(_now()),
        ),
    )


def ensure_schema(db: sqlite3.Connection) -> None:
    """Create the authority tables in the existing Amosclaud auth database."""

    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS amosclaud_credentials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_user_id INTEGER NOT NULL,
            credential_type TEXT NOT NULL
                CHECK(credential_type IN ('api_key','token','action')),
            name TEXT NOT NULL,
            prefix TEXT NOT NULL,
            secret_hash TEXT NOT NULL UNIQUE,
            scopes_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            last_used_at TEXT,
            revoked_at TEXT,
            FOREIGN KEY(owner_user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_amosclaud_credentials_owner
            ON amosclaud_credentials(owner_user_id, revoked_at);

        CREATE TABLE IF NOT EXISTS amosclaud_workspace_grants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            subject TEXT NOT NULL,
            prefix TEXT NOT NULL,
            secret_hash TEXT NOT NULL UNIQUE,
            scopes_json TEXT NOT NULL,
            created_by_user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            last_used_at TEXT,
            revoked_at TEXT,
            FOREIGN KEY(created_by_user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_amosclaud_workspace_grants_workspace
            ON amosclaud_workspace_grants(workspace_id, revoked_at, expires_at);

        CREATE TABLE IF NOT EXISTS amosclaud_authority_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            principal_type TEXT NOT NULL,
            principal_id INTEGER NOT NULL,
            actor_user_id INTEGER,
            event TEXT NOT NULL,
            details_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_amosclaud_authority_events_principal
            ON amosclaud_authority_events(principal_type, principal_id, created_at);
        """
    )


def _platform_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "type": str(row["credential_type"]),
        "name": str(row["name"]),
        "prefix": str(row["prefix"]),
        "scopes": _loads_scopes(row["scopes_json"]),
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "last_used_at": row["last_used_at"],
        "revoked_at": row["revoked_at"],
        "expiration_policy": "manual_revocation"
        if row["expires_at"] is None
        else "expires",
    }


def _grant_payload(row: sqlite3.Row) -> dict[str, Any]:
    expiry = _expires_at(row["expires_at"])
    status = (
        "revoked"
        if row["revoked_at"]
        else "expired"
        if expiry and expiry <= _now()
        else "active"
    )
    return {
        "id": int(row["id"]),
        "workspace_id": str(row["workspace_id"]),
        "provider": str(row["provider"]),
        "subject": str(row["subject"]),
        "prefix": str(row["prefix"]),
        "scopes": _loads_scopes(row["scopes_json"]),
        "created_by_user_id": int(row["created_by_user_id"]),
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "last_used_at": row["last_used_at"],
        "revoked_at": row["revoked_at"],
        "status": status,
        "expiration_policy": "required_workspace_expiry",
    }


def _credential_row(db: sqlite3.Connection, credential_id: int) -> sqlite3.Row | None:
    return db.execute(
        "SELECT * FROM amosclaud_credentials WHERE id=?",
        (int(credential_id),),
    ).fetchone()


def _grant_row(db: sqlite3.Connection, grant_id: int) -> sqlite3.Row | None:
    return db.execute(
        "SELECT * FROM amosclaud_workspace_grants WHERE id=?",
        (int(grant_id),),
    ).fetchone()


def _assert_platform_scope_policy(scopes: list[str], *, is_admin: bool) -> None:
    if "authority:admin" in scopes and not is_admin:
        raise ScopeError("authority:admin is reserved for Amosclaud platform administrators")


def issue_platform_credential(
    *,
    owner_user_id: int,
    name: str,
    credential_type: str,
    scopes: Iterable[str],
    actor_user_id: int | None = None,
    is_admin: bool = False,
) -> dict[str, Any]:
    """Issue an Amosclaud-owned credential with manual-revocation lifetime."""

    if credential_type not in PLATFORM_CREDENTIAL_KINDS:
        raise AuthorityError("Credential type must be api_key, token, or action")
    normalised_name = _normalise_name(name)
    normalised_scopes = _normalise_scopes(scopes, allowed=PLATFORM_SCOPES)
    _assert_platform_scope_policy(normalised_scopes, is_admin=is_admin)
    raw = _new_secret(_PREFIXES[credential_type])
    now = _iso(_now())
    with auth._connect() as db:
        ensure_schema(db)
        if not db.execute("SELECT 1 FROM users WHERE id=?", (int(owner_user_id),)).fetchone():
            raise CredentialNotFound("Credential owner account was not found")
        cursor = db.execute(
            """INSERT INTO amosclaud_credentials(
                   owner_user_id,credential_type,name,prefix,secret_hash,
                   scopes_json,created_at,expires_at
               ) VALUES (?,?,?,?,?,?,?,NULL)""",
            (
                int(owner_user_id),
                credential_type,
                normalised_name,
                raw[:18],
                _hash_secret(raw),
                json.dumps(normalised_scopes, separators=(",", ":")),
                now,
            ),
        )
        credential_id = int(cursor.lastrowid)
        _record_event(
            db,
            principal_type="platform_credential",
            principal_id=credential_id,
            actor_user_id=actor_user_id if actor_user_id is not None else owner_user_id,
            event="created",
            details={"type": credential_type, "scopes": normalised_scopes},
        )
        row = _credential_row(db, credential_id)
        db.commit()
    if not row:  # pragma: no cover - guarded by the insert above
        raise CredentialNotFound("Issued credential could not be loaded")
    payload = _platform_payload(row)
    payload["secret"] = raw
    payload["warning"] = "Copy this secret now. Amosclaud stores only its secure hash."
    return payload


def list_platform_credentials(
    *, owner_user_id: int | None = None, include_revoked: bool = False
) -> list[dict[str, Any]]:
    with auth._connect() as db:
        ensure_schema(db)
        clauses: list[str] = []
        values: list[Any] = []
        if owner_user_id is not None:
            clauses.append("owner_user_id=?")
            values.append(int(owner_user_id))
        if not include_revoked:
            clauses.append("revoked_at IS NULL")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = db.execute(
            f"SELECT * FROM amosclaud_credentials{where} ORDER BY id DESC",
            values,
        ).fetchall()
    return [_platform_payload(row) for row in rows]


def revoke_platform_credential(
    credential_id: int, *, actor_user_id: int, is_admin: bool = False
) -> None:
    now = _iso(_now())
    with auth._connect() as db:
        ensure_schema(db)
        row = _credential_row(db, credential_id)
        if not row or (not is_admin and int(row["owner_user_id"]) != int(actor_user_id)):
            raise CredentialNotFound("Active Amosclaud credential was not found")
        if not row["revoked_at"]:
            db.execute(
                "UPDATE amosclaud_credentials SET revoked_at=? WHERE id=?",
                (now, int(credential_id)),
            )
            _record_event(
                db,
                principal_type="platform_credential",
                principal_id=int(credential_id),
                actor_user_id=actor_user_id,
                event="revoked",
            )
            db.commit()


def rotate_platform_credential(
    credential_id: int, *, actor_user_id: int, is_admin: bool = False
) -> dict[str, Any]:
    raw = ""
    now = _iso(_now())
    with auth._connect() as db:
        ensure_schema(db)
        old = _credential_row(db, credential_id)
        if not old or (not is_admin and int(old["owner_user_id"]) != int(actor_user_id)):
            raise CredentialNotFound("Active Amosclaud credential was not found")
        if not _active(old):
            raise CredentialNotFound("Only an active Amosclaud credential can be rotated")
        raw = _new_secret(_PREFIXES[str(old["credential_type"])])
        cursor = db.execute(
            """INSERT INTO amosclaud_credentials(
                   owner_user_id,credential_type,name,prefix,secret_hash,
                   scopes_json,created_at,expires_at
               ) VALUES (?,?,?,?,?,?,?,NULL)""",
            (
                int(old["owner_user_id"]),
                old["credential_type"],
                old["name"],
                raw[:18],
                _hash_secret(raw),
                old["scopes_json"],
                now,
            ),
        )
        replacement_id = int(cursor.lastrowid)
        db.execute(
            "UPDATE amosclaud_credentials SET revoked_at=? WHERE id=?",
            (now, int(credential_id)),
        )
        _record_event(
            db,
            principal_type="platform_credential",
            principal_id=int(credential_id),
            actor_user_id=actor_user_id,
            event="rotated",
            details={"replacement_id": replacement_id},
        )
        _record_event(
            db,
            principal_type="platform_credential",
            principal_id=replacement_id,
            actor_user_id=actor_user_id,
            event="created",
            details={"rotated_from": int(credential_id)},
        )
        row = _credential_row(db, replacement_id)
        db.commit()
    if not row:  # pragma: no cover - guarded by the insert above
        raise CredentialNotFound("Replacement credential could not be loaded")
    payload = _platform_payload(row)
    payload["secret"] = raw
    payload["warning"] = "The previous credential is revoked. Copy this replacement now."
    return payload


def issue_workspace_grant(
    *,
    workspace_id: str,
    provider: str,
    subject: str,
    scopes: Iterable[str],
    expires_in_days: int,
    created_by_user_id: int,
    actor_user_id: int | None = None,
) -> dict[str, Any]:
    """Issue an expiring third-party grant for an existing workspace."""

    if not isinstance(expires_in_days, int) or isinstance(expires_in_days, bool):
        raise AuthorityError("expires_in_days must be an integer")
    if expires_in_days < MIN_THIRD_PARTY_GRANT_DAYS:
        raise AuthorityError(
            "Third-party workspace access must expire in at least "
            f"{MIN_THIRD_PARTY_GRANT_DAYS} days"
        )
    if expires_in_days > MAX_THIRD_PARTY_GRANT_DAYS:
        raise AuthorityError(
            f"Third-party workspace access cannot exceed {MAX_THIRD_PARTY_GRANT_DAYS} days"
        )
    workspace = _normalise_workspace_id(workspace_id)
    external_provider = _normalise_provider(provider)
    external_subject = _normalise_subject(subject)
    normalised_scopes = _normalise_scopes(scopes, allowed=THIRD_PARTY_SCOPES)
    raw = _new_secret("amos_ext_")
    created = _now()
    now = _iso(created)
    expiry = _iso(created + timedelta(days=expires_in_days))
    with auth._connect() as db:
        ensure_schema(db)
        if not db.execute("SELECT 1 FROM users WHERE id=?", (int(created_by_user_id),)).fetchone():
            raise CredentialNotFound("Grant owner account was not found")
        cursor = db.execute(
            """INSERT INTO amosclaud_workspace_grants(
                   workspace_id,provider,subject,prefix,secret_hash,scopes_json,
                   created_by_user_id,created_at,expires_at
               ) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                workspace,
                external_provider,
                external_subject,
                raw[:18],
                _hash_secret(raw),
                json.dumps(normalised_scopes, separators=(",", ":")),
                int(created_by_user_id),
                now,
                expiry,
            ),
        )
        grant_id = int(cursor.lastrowid)
        _record_event(
            db,
            principal_type="workspace_grant",
            principal_id=grant_id,
            actor_user_id=(
                actor_user_id if actor_user_id is not None else created_by_user_id
            ),
            event="created",
            details={
                "workspace_id": workspace,
                "provider": external_provider,
                "scopes": normalised_scopes,
                "expires_in_days": expires_in_days,
            },
        )
        row = _grant_row(db, grant_id)
        db.commit()
    if not row:  # pragma: no cover - guarded by the insert above
        raise CredentialNotFound("Issued workspace grant could not be loaded")
    payload = _grant_payload(row)
    payload["secret"] = raw
    payload["warning"] = "Copy this secret now. Amosclaud stores only its secure hash."
    return payload


def list_workspace_grants(
    workspace_id: str, *, include_revoked: bool = False
) -> list[dict[str, Any]]:
    workspace = _normalise_workspace_id(workspace_id)
    with auth._connect() as db:
        ensure_schema(db)
        clauses = ["workspace_id=?"]
        values: list[Any] = [workspace]
        if not include_revoked:
            clauses.append("revoked_at IS NULL")
        rows = db.execute(
            "SELECT * FROM amosclaud_workspace_grants WHERE "
            + " AND ".join(clauses)
            + " ORDER BY id DESC",
            values,
        ).fetchall()
    return [_grant_payload(row) for row in rows]


def revoke_workspace_grant(
    grant_id: int, *, actor_user_id: int
) -> None:
    now = _iso(_now())
    with auth._connect() as db:
        ensure_schema(db)
        row = _grant_row(db, grant_id)
        if not row:
            raise CredentialNotFound("Workspace grant was not found")
        if not row["revoked_at"]:
            db.execute(
                "UPDATE amosclaud_workspace_grants SET revoked_at=? WHERE id=?",
                (now, int(grant_id)),
            )
            _record_event(
                db,
                principal_type="workspace_grant",
                principal_id=int(grant_id),
                actor_user_id=actor_user_id,
                event="revoked",
            )
            db.commit()


def rotate_workspace_grant(
    grant_id: int,
    *,
    workspace_id: str | None = None,
    expires_in_days: int,
    actor_user_id: int,
) -> dict[str, Any]:
    with auth._connect() as db:
        ensure_schema(db)
        old = _grant_row(db, grant_id)
        if not old or not _active(old):
            raise CredentialNotFound("Only an active workspace grant can be rotated")
        if workspace_id is not None and old["workspace_id"] != _normalise_workspace_id(
            workspace_id
        ):
            raise CredentialNotFound("Workspace grant was not found")
        # Keep the policy in one place while retaining the original grant's
        # workspace/provider/subject/scope binding.
        if expires_in_days < MIN_THIRD_PARTY_GRANT_DAYS:
            raise AuthorityError(
                "Third-party workspace access must expire in at least "
                f"{MIN_THIRD_PARTY_GRANT_DAYS} days"
            )
        if expires_in_days > MAX_THIRD_PARTY_GRANT_DAYS:
            raise AuthorityError(
                f"Third-party workspace access cannot exceed {MAX_THIRD_PARTY_GRANT_DAYS} days"
            )
        raw = _new_secret("amos_ext_")
        now_dt = _now()
        now = _iso(now_dt)
        expiry = _iso(now_dt + timedelta(days=expires_in_days))
        cursor = db.execute(
            """INSERT INTO amosclaud_workspace_grants(
                   workspace_id,provider,subject,prefix,secret_hash,scopes_json,
                   created_by_user_id,created_at,expires_at
               ) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                old["workspace_id"],
                old["provider"],
                old["subject"],
                raw[:18],
                _hash_secret(raw),
                old["scopes_json"],
                old["created_by_user_id"],
                now,
                expiry,
            ),
        )
        replacement_id = int(cursor.lastrowid)
        db.execute(
            "UPDATE amosclaud_workspace_grants SET revoked_at=? WHERE id=?",
            (now, int(grant_id)),
        )
        _record_event(
            db,
            principal_type="workspace_grant",
            principal_id=int(grant_id),
            actor_user_id=actor_user_id,
            event="rotated",
            details={"replacement_id": replacement_id},
        )
        _record_event(
            db,
            principal_type="workspace_grant",
            principal_id=replacement_id,
            actor_user_id=actor_user_id,
            event="created",
            details={"rotated_from": int(grant_id), "expires_in_days": expires_in_days},
        )
        row = _grant_row(db, replacement_id)
        db.commit()
    if not row:  # pragma: no cover - guarded by the insert above
        raise CredentialNotFound("Replacement workspace grant could not be loaded")
    payload = _grant_payload(row)
    payload["secret"] = raw
    payload["warning"] = "The previous grant is revoked. Copy this replacement now."
    return payload


def scope_allowed(principal: dict[str, Any], required_scope: str | None) -> bool:
    if not required_scope:
        return True
    scopes = set(principal.get("scopes") or [])
    return required_scope in scopes or "authority:admin" in scopes


def authenticate_credential(
    raw: str | None, *, workspace_id: str | None = None
) -> dict[str, Any] | None:
    """Return a sanitized principal for an active first- or third-party secret."""

    secret = str(raw or "").strip()
    if not secret:
        return None
    digest = _hash_secret(secret)
    now = _now()
    with auth._connect() as db:
        ensure_schema(db)
        if secret.startswith(tuple(_PREFIXES.values())):
            row = db.execute(
                """SELECT c.*,u.name,u.email,u.is_admin,u.provider
                   FROM amosclaud_credentials c
                   JOIN users u ON u.id=c.owner_user_id
                   WHERE c.secret_hash=?""",
                (digest,),
            ).fetchone()
            if not row or not _active(row, now):
                return None
            used_at = _iso(now)
            db.execute(
                "UPDATE amosclaud_credentials SET last_used_at=? WHERE id=?",
                (used_at, row["id"]),
            )
            db.commit()
            return {
                "authenticated": True,
                "principal_type": "amosclaud",
                "credential_type": str(row["credential_type"]),
                "credential_id": int(row["id"]),
                "user_id": int(row["owner_user_id"]),
                "name": row["name"],
                "email": row["email"],
                "is_admin": bool(row["is_admin"]),
                "provider": row["provider"],
                "scopes": _loads_scopes(row["scopes_json"]),
                "workspace_id": None,
                "expires_at": row["expires_at"],
            }

        if not secret.startswith("amos_ext_"):
            return None
        row = db.execute(
            """SELECT g.*,u.name,u.email,u.is_admin,u.provider
               FROM amosclaud_workspace_grants g
               JOIN users u ON u.id=g.created_by_user_id
               WHERE g.secret_hash=?""",
            (digest,),
        ).fetchone()
        if not row or not _active(row, now):
            return None
        # A third-party grant must always be presented with its workspace
        # context; accepting it without that binding would turn a workspace
        # authorization into an account-wide credential.
        if workspace_id is None or str(workspace_id).strip() != row["workspace_id"]:
            return None
        used_at = _iso(now)
        db.execute(
            "UPDATE amosclaud_workspace_grants SET last_used_at=? WHERE id=?",
            (used_at, row["id"]),
        )
        db.commit()
        return {
            "authenticated": True,
            "principal_type": "third_party_workspace_grant",
            "credential_type": "workspace_grant",
            "credential_id": int(row["id"]),
            "user_id": int(row["created_by_user_id"]),
            "name": row["name"],
            "email": row["email"],
            "is_admin": bool(row["is_admin"]),
            "provider": row["provider"],
            "external_provider": row["provider"],
            "external_subject": row["subject"],
            "scopes": _loads_scopes(row["scopes_json"]),
            "workspace_id": row["workspace_id"],
            "expires_at": row["expires_at"],
        }


def verify_credential(
    raw: str | None,
    *,
    required_scope: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any] | None:
    """Authenticate a secret and attach the result of a scope check."""

    principal = authenticate_credential(raw, workspace_id=workspace_id)
    if principal is None:
        return None
    principal = dict(principal)
    principal["required_scope"] = required_scope
    principal["scope_granted"] = scope_allowed(principal, required_scope)
    return principal


__all__ = [
    "AuthorityError",
    "CredentialNotFound",
    "MAX_THIRD_PARTY_GRANT_DAYS",
    "MIN_THIRD_PARTY_GRANT_DAYS",
    "PLATFORM_CREDENTIAL_KINDS",
    "PLATFORM_SCOPES",
    "ScopeError",
    "THIRD_PARTY_SCOPES",
    "authenticate_credential",
    "ensure_schema",
    "issue_platform_credential",
    "issue_workspace_grant",
    "list_platform_credentials",
    "list_workspace_grants",
    "revoke_platform_credential",
    "revoke_workspace_grant",
    "rotate_platform_credential",
    "rotate_workspace_grant",
    "scope_allowed",
    "verify_credential",
]
