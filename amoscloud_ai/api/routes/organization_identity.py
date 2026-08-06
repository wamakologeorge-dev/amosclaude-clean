"""Organization-ID accounts, membership control, and recovery."""

from __future__ import annotations

import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import DB_PATH
from amoscloud_ai.api.routes.auth import _connect as _auth_connect
from amoscloud_ai.api.routes.auth import (
    _create_session,
    _hash_password,
    _set_session_cookie,
    _token_hash,
    _verify_password,
    get_user_from_session,
)

router = APIRouter(prefix="/organization-access", tags=["organization-access"])
_ORG_ID_RE = re.compile(r"^[0-9]{5}$")
_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{2,31}$")
_MEMBER_RE = re.compile(r"^[0-9]{4}$")
_SCHEMA_VERSION = 1


class OrganizationRegistration(BaseModel):
    organization_id: str = Field(..., min_length=5, max_length=5)
    organization_name: str = Field(..., min_length=2, max_length=100)
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=10, max_length=200)


class OrganizationJoin(BaseModel):
    organization_id: str = Field(..., min_length=5, max_length=5)
    access_code: str = Field(..., min_length=8, max_length=24)
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=10, max_length=200)


class OrganizationLogin(BaseModel):
    organization_id: str = Field(..., min_length=5, max_length=5)
    username_or_member_id: str = Field(..., min_length=3, max_length=40)
    password: str = Field(..., min_length=1, max_length=200)


class RecoveryRequest(BaseModel):
    organization_id: str = Field(..., min_length=5, max_length=5)
    username_or_member_id: str = Field(..., min_length=3, max_length=40)
    recovery_code: str = Field(..., min_length=16, max_length=32)
    new_password: str = Field(..., min_length=10, max_length=200)


class JoinCodeRequest(BaseModel):
    expires_minutes: int = Field(default=30, ge=5, le=1440)
    uses: int = Field(default=1, ge=1, le=25)


class OrganizationIdentifierChange(BaseModel):
    organization_id: str = Field(..., min_length=5, max_length=5)


class OwnershipTransfer(BaseModel):
    member_number: str = Field(..., min_length=4, max_length=4)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in db.execute(f"PRAGMA table_info({table})")}


def _ensure_column(db: sqlite3.Connection, table: str, definition: str) -> None:
    if definition.split()[0] not in _columns(db, table):
        db.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def _validate_org_id(value: str) -> str:
    normalized = value.strip()
    if not _ORG_ID_RE.fullmatch(normalized):
        raise HTTPException(
            status_code=422,
            detail="Organization ID must contain exactly five numbers",
        )
    return normalized


def _validate_username(value: str) -> str:
    normalized = value.strip()
    if not _USERNAME_RE.fullmatch(normalized):
        raise HTTPException(
            status_code=422,
            detail=(
                "Username must start with a letter and use 3-32 letters, "
                "numbers, dots, underscores, or hyphens"
            ),
        )
    return normalized


def _validate_organization_name(value: str) -> str:
    normalized = value.strip()
    if len(normalized) < 2:
        raise HTTPException(
            status_code=422,
            detail="Organization name must contain at least two visible characters",
        )
    return normalized


def _canonical_secret(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value).upper()


def _next_org_id(db: sqlite3.Connection) -> str:
    for _ in range(1000):
        value = f"{secrets.randbelow(90_000) + 10_000:05d}"
        if not db.execute("SELECT 1 FROM organizations WHERE public_id=?", (value,)).fetchone():
            return value
    raise HTTPException(status_code=503, detail="Organization ID allocation is busy")


def _next_member_number(db: sqlite3.Connection, organization_id: int) -> str:
    for _ in range(1000):
        value = f"{secrets.randbelow(9000) + 1000:04d}"
        if not db.execute(
            """SELECT 1 FROM organization_members
               WHERE organization_id=? AND member_number=?""",
            (organization_id, value),
        ).fetchone():
            return value
    raise HTTPException(status_code=503, detail="Member ID allocation is busy")


def _safe_existing_username(name: str, user_id: int) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]", "", name.strip())[:32]
    if len(value) < 3 or not value[0].isalpha():
        return f"member{user_id}"
    return value


def _backfill(db: sqlite3.Connection) -> None:
    now = _now()
    organizations = db.execute(
        """SELECT id,public_id,status,updated_at FROM organizations
           WHERE public_id IS NULL OR public_id='' OR updated_at IS NULL"""
    ).fetchall()
    for row in organizations:
        db.execute(
            "UPDATE organizations SET public_id=?,status=?,updated_at=? WHERE id=?",
            (
                row["public_id"] or _next_org_id(db),
                row["status"] or "active",
                row["updated_at"] or now,
                row["id"],
            ),
        )

    rows = db.execute(
        """SELECT m.organization_id,m.user_id,m.username,m.member_number,
                  m.status,m.updated_at,u.name
           FROM organization_members m JOIN users u ON u.id=m.user_id
           WHERE m.username IS NULL OR m.username='' OR m.member_number IS NULL
              OR m.member_number='' OR m.updated_at IS NULL"""
    ).fetchall()
    for row in rows:
        username = row["username"] or _safe_existing_username(
            str(row["name"]), int(row["user_id"])
        )
        candidate = username
        suffix = 1
        while db.execute(
            """SELECT 1 FROM organization_members
               WHERE organization_id=? AND username=? COLLATE NOCASE
                 AND user_id<>?""",
            (row["organization_id"], candidate, row["user_id"]),
        ).fetchone():
            suffix += 1
            candidate = f"{username[: 32 - len(str(suffix))]}{suffix}"
        db.execute(
            """UPDATE organization_members
               SET username=?,member_number=?,status=?,updated_at=?
               WHERE organization_id=? AND user_id=?""",
            (
                candidate,
                row["member_number"]
                or _next_member_number(db, int(row["organization_id"])),
                row["status"] or "active",
                row["updated_at"] or now,
                row["organization_id"],
                row["user_id"],
            ),
        )


def _migrate_once(db: sqlite3.Connection) -> None:
    row = db.execute(
        "SELECT value FROM organization_schema_meta WHERE key='identity_version'"
    ).fetchone()
    version = int(row["value"]) if row else 0
    if version >= _SCHEMA_VERSION:
        return
    _backfill(db)
    db.execute(
        """INSERT INTO organization_schema_meta(key,value)
           VALUES ('identity_version',?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
        (str(_SCHEMA_VERSION),),
    )


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _auth_connect():
        pass
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS organizations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE COLLATE NOCASE,
            owner_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS organization_members (
            organization_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('owner','admin','developer','viewer')),
            created_at TEXT NOT NULL,
            PRIMARY KEY(organization_id,user_id),
            FOREIGN KEY(organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS organization_join_secrets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            organization_id INTEGER NOT NULL,
            secret_hash TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            remaining_uses INTEGER NOT NULL,
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            revoked_at TEXT,
            FOREIGN KEY(organization_id) REFERENCES organizations(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS organization_recovery_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            organization_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            code_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            used_at TEXT,
            FOREIGN KEY(organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS organization_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            organization_id INTEGER NOT NULL,
            actor_user_id INTEGER,
            target_user_id INTEGER,
            action TEXT NOT NULL,
            detail TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(organization_id) REFERENCES organizations(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS organization_schema_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """)
    _ensure_column(db, "organizations", "public_id TEXT")
    _ensure_column(db, "organizations", "status TEXT NOT NULL DEFAULT 'active'")
    _ensure_column(db, "organizations", "updated_at TEXT")
    _ensure_column(db, "organization_members", "username TEXT COLLATE NOCASE")
    _ensure_column(db, "organization_members", "member_number TEXT")
    _ensure_column(
        db,
        "organization_members",
        "status TEXT NOT NULL DEFAULT 'active'",
    )
    _ensure_column(db, "organization_members", "removed_at TEXT")
    _ensure_column(db, "organization_members", "updated_at TEXT")
    _migrate_once(db)
    db.executescript("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_organization_public_id
        ON organizations(public_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_organization_member_username
        ON organization_members(organization_id,username);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_organization_member_number
        ON organization_members(organization_id,member_number);
        CREATE INDEX IF NOT EXISTS idx_organization_join_secret
        ON organization_join_secrets(organization_id,secret_hash);
        CREATE INDEX IF NOT EXISTS idx_organization_recovery
        ON organization_recovery_codes(organization_id,user_id,code_hash);
        """)
    db.commit()
    return db


def _current_user(amos_session: str | None = Cookie(default=None)) -> sqlite3.Row:
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _membership(db: sqlite3.Connection, public_id: str, user_id: int) -> sqlite3.Row:
    row = db.execute(
        """SELECT o.id AS organization_id,o.public_id,o.name AS organization_name,
                  o.slug,m.user_id,m.username,m.member_number,m.role,
                  m.status AS member_status
           FROM organizations o
           JOIN organization_members m ON m.organization_id=o.id
           WHERE o.public_id=? AND m.user_id=?
             AND o.status='active' AND m.status='active'""",
        (public_id, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Organization not found")
    return row


def _identity(
    db: sqlite3.Connection, public_id: str, username_or_member_id: str
) -> sqlite3.Row | None:
    identifier = username_or_member_id.strip()
    member_number = None
    if identifier.startswith(f"{public_id}-"):
        suffix = identifier[len(public_id) + 1 :]
        if _MEMBER_RE.fullmatch(suffix):
            member_number = suffix
    field = "m.member_number" if member_number else "m.username"
    value = member_number or identifier
    return db.execute(
        f"""SELECT o.id AS organization_id,o.public_id,
                   o.name AS organization_name,o.slug,m.user_id,m.username,
                   m.member_number,m.role,m.status AS member_status,
                   u.password_hash
            FROM organizations o
            JOIN organization_members m ON m.organization_id=o.id
            JOIN users u ON u.id=m.user_id
            WHERE o.public_id=? AND {field}=? COLLATE NOCASE
              AND o.status='active' AND m.status='active'""",
        (public_id, value),
    ).fetchone()


def _member_id(public_id: str, member_number: str) -> str:
    return f"{public_id}-{member_number}"


def _payload(row: sqlite3.Row) -> dict:
    member_id = _member_id(row["public_id"], row["member_number"])
    return {
        "organization_id": row["public_id"],
        "organization_name": row["organization_name"],
        "username": row["username"],
        "member_id": member_id,
        "account_id": member_id,
        "role": row["role"],
        "status": row["member_status"],
    }


def _audit(
    db: sqlite3.Connection,
    organization_id: int,
    action: str,
    actor_user_id: int | None = None,
    target_user_id: int | None = None,
    detail: str | None = None,
) -> None:
    db.execute(
        """INSERT INTO organization_audit_log(
               organization_id,actor_user_id,target_user_id,action,detail,created_at
           ) VALUES (?,?,?,?,?,?)""",
        (
            organization_id,
            actor_user_id,
            target_user_id,
            action,
            detail,
            _now(),
        ),
    )


def _recovery_code() -> str:
    raw = secrets.token_hex(8).upper()
    return "-".join(raw[index : index + 4] for index in range(0, 16, 4))


def _create_recovery_codes(
    db: sqlite3.Connection, organization_id: int, user_id: int, count: int
) -> list[str]:
    codes = [_recovery_code() for _ in range(count)]
    db.executemany(
        """INSERT INTO organization_recovery_codes(
               organization_id,user_id,code_hash,created_at
           ) VALUES (?,?,?,?)""",
        [
            (
                organization_id,
                user_id,
                _token_hash(_canonical_secret(code)),
                _now(),
            )
            for code in codes
        ],
    )
    return codes


def _native_email() -> str:
    return f"org-{secrets.token_hex(16)}@accounts.amosclaud.invalid"


def _create_native_user(
    db: sqlite3.Connection,
    username: str,
    password: str,
) -> int:
    cursor = db.execute(
        """INSERT INTO users(
               name,email,password_hash,provider,is_admin,created_at
           ) VALUES (?,?,?,'organization',0,?)""",
        (username, _native_email(), _hash_password(password), _now()),
    )
    return int(cursor.lastrowid)


@router.post("/register", status_code=201)
def register(body: OrganizationRegistration, response: Response) -> dict:
    public_id = _validate_org_id(body.organization_id)
    organization_name = _validate_organization_name(body.organization_name)
    username = _validate_username(body.username)
    now = _now()
    with _db() as db:
        if db.execute("SELECT 1 FROM organizations WHERE public_id=?", (public_id,)).fetchone():
            raise HTTPException(status_code=409, detail="Organization ID is in use")
        member_number = f"{secrets.randbelow(9000) + 1000:04d}"
        try:
            user_id = _create_native_user(db, username, body.password)
            cursor = db.execute(
                """INSERT INTO organizations(
                       name,slug,owner_id,created_at,public_id,status,updated_at
                   ) VALUES (?,?,?,?,?,'active',?)""",
                (
                    organization_name,
                    f"org-{public_id}",
                    user_id,
                    now,
                    public_id,
                    now,
                ),
            )
            organization_id = int(cursor.lastrowid)
            db.execute(
                """INSERT INTO organization_members(
                       organization_id,user_id,role,created_at,username,
                       member_number,status,updated_at
                   ) VALUES (?,?,'owner',?,?,?,'active',?)""",
                (
                    organization_id,
                    user_id,
                    now,
                    username,
                    member_number,
                    now,
                ),
            )
            recovery_codes = _create_recovery_codes(db, organization_id, user_id, 3)
            _audit(
                db,
                organization_id,
                "organization.created",
                user_id,
                user_id,
            )
            db.commit()
        except sqlite3.IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Organization ID or username is in use",
            ) from exc
        token = _create_session(db, user_id)
    _set_session_cookie(response, token)
    return {
        "organization_id": public_id,
        "username": username,
        "member_id": _member_id(public_id, member_number),
        "account_id": _member_id(public_id, member_number),
        "role": "owner",
        "recovery_codes": recovery_codes,
        "recovery_notice": (
            "Save these three codes now. Amosclaud stores only their hashes "
            "and cannot display them again."
        ),
    }


@router.post("/login")
def login(body: OrganizationLogin, response: Response) -> dict:
    public_id = _validate_org_id(body.organization_id)
    with _db() as db:
        identity = _identity(db, public_id, body.username_or_member_id)
        if not identity or not _verify_password(body.password, identity["password_hash"]):
            raise HTTPException(
                status_code=401,
                detail="Invalid organization ID, username, member ID, or password",
            )
        token = _create_session(db, int(identity["user_id"]))
        _audit(
            db,
            int(identity["organization_id"]),
            "member.login",
            int(identity["user_id"]),
        )
        db.commit()
        result = _payload(identity)
    _set_session_cookie(response, token)
    return result


@router.post("/{public_id}/join-code", status_code=201)
def create_join_code(
    public_id: str,
    body: JoinCodeRequest,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    public_id = _validate_org_id(public_id)
    raw = f"{secrets.randbelow(100_000_000):08d}"
    access_code = f"{raw[:4]}-{raw[4:]}"
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=body.expires_minutes)
    with _db() as db:
        membership = _membership(db, public_id, int(user["id"]))
        if membership["role"] not in {"owner", "admin"}:
            raise HTTPException(status_code=403, detail="Administrator access required")
        db.execute(
            """INSERT INTO organization_join_secrets(
                   organization_id,secret_hash,expires_at,remaining_uses,
                   created_by,created_at
               ) VALUES (?,?,?,?,?,?)""",
            (
                membership["organization_id"],
                _token_hash(_canonical_secret(access_code)),
                expires_at.isoformat(),
                body.uses,
                user["id"],
                now.isoformat(),
            ),
        )
        _audit(
            db,
            int(membership["organization_id"]),
            "join_code.created",
            int(user["id"]),
            detail=f"uses={body.uses}",
        )
        db.commit()
    return {
        "organization_id": public_id,
        "access_code": access_code,
        "uses": body.uses,
        "expires_at": expires_at.isoformat(),
        "notice": "Share privately. Amosclaud stores only the code hash.",
    }


@router.post("/join", status_code=201)
def join(body: OrganizationJoin, response: Response) -> dict:
    public_id = _validate_org_id(body.organization_id)
    username = _validate_username(body.username)
    now = _now()
    with _db() as db:
        organization = db.execute(
            """SELECT id,name FROM organizations
               WHERE public_id=? AND status='active'""",
            (public_id,),
        ).fetchone()
        if not organization:
            raise HTTPException(status_code=400, detail="Invalid organization access")
        secret = db.execute(
            """SELECT id FROM organization_join_secrets
               WHERE organization_id=? AND secret_hash=? AND revoked_at IS NULL
                 AND expires_at>? AND remaining_uses>0
               ORDER BY id DESC LIMIT 1""",
            (
                organization["id"],
                _token_hash(_canonical_secret(body.access_code)),
                now,
            ),
        ).fetchone()
        if not secret:
            raise HTTPException(status_code=400, detail="Invalid organization access")
        if db.execute(
            """SELECT 1 FROM organization_members
               WHERE organization_id=? AND username=? COLLATE NOCASE""",
            (organization["id"], username),
        ).fetchone():
            raise HTTPException(status_code=409, detail="Username is in use")
        member_number = _next_member_number(db, int(organization["id"]))
        try:
            cursor = db.execute(
                """UPDATE organization_join_secrets
                   SET remaining_uses=remaining_uses-1,
                       revoked_at=CASE WHEN remaining_uses=1 THEN ? ELSE revoked_at END
                   WHERE id=? AND revoked_at IS NULL
                     AND expires_at>? AND remaining_uses>0""",
                (now, secret["id"], now),
            )
            if cursor.rowcount != 1:
                raise HTTPException(status_code=400, detail="Invalid organization access")
            user_id = _create_native_user(db, username, body.password)
            db.execute(
                """INSERT INTO organization_members(
                       organization_id,user_id,role,created_at,username,
                       member_number,status,updated_at
                   ) VALUES (?,?,'developer',?,?,?,'active',?)""",
                (
                    organization["id"],
                    user_id,
                    now,
                    username,
                    member_number,
                    now,
                ),
            )
            recovery_codes = _create_recovery_codes(db, int(organization["id"]), user_id, 3)
            _audit(
                db,
                int(organization["id"]),
                "member.joined",
                target_user_id=user_id,
                detail=f"username={username}",
            )
            db.commit()
        except sqlite3.IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="Member identity is in use") from exc
        except HTTPException:
            db.rollback()
            raise
        token = _create_session(db, user_id)
    _set_session_cookie(response, token)
    return {
        "organization_id": public_id,
        "organization_name": organization["name"],
        "username": username,
        "member_id": _member_id(public_id, member_number),
        "account_id": _member_id(public_id, member_number),
        "role": "developer",
        "recovery_codes": recovery_codes,
        "recovery_notice": (
            "Save these three codes now. Amosclaud stores only their hashes "
            "and cannot display them again."
        ),
    }


@router.post("/recover")
def recover(body: RecoveryRequest) -> dict:
    public_id = _validate_org_id(body.organization_id)
    with _db() as db:
        identity = _identity(db, public_id, body.username_or_member_id)
        if not identity:
            raise HTTPException(status_code=400, detail="Invalid recovery information")
        recovery = db.execute(
            """SELECT id FROM organization_recovery_codes
               WHERE organization_id=? AND user_id=? AND code_hash=?
                 AND used_at IS NULL ORDER BY id LIMIT 1""",
            (
                identity["organization_id"],
                identity["user_id"],
                _token_hash(_canonical_secret(body.recovery_code)),
            ),
        ).fetchone()
        if not recovery:
            raise HTTPException(status_code=400, detail="Invalid recovery information")
        db.execute(
            "UPDATE organization_recovery_codes SET used_at=? WHERE id=?",
            (_now(), recovery["id"]),
        )
        db.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (_hash_password(body.new_password), identity["user_id"]),
        )
        db.execute("DELETE FROM sessions WHERE user_id=?", (identity["user_id"],))
        replacement = _create_recovery_codes(
            db, int(identity["organization_id"]), int(identity["user_id"]), 1
        )[0]
        _audit(
            db,
            int(identity["organization_id"]),
            "member.recovered",
            int(identity["user_id"]),
            int(identity["user_id"]),
        )
        db.commit()
        result = _payload(identity)
    return {
        **result,
        "password_reset": True,
        "replacement_recovery_code": replacement,
        "recovery_notice": "The used code is invalid. Save the replacement now.",
    }


@router.get("/current")
def current(user: sqlite3.Row = Depends(_current_user)) -> list[dict]:
    with _db() as db:
        rows = db.execute(
            """SELECT o.id AS organization_id,o.public_id,
                      o.name AS organization_name,o.slug,m.user_id,m.username,
                      m.member_number,m.role,m.status AS member_status
               FROM organizations o
               JOIN organization_members m ON m.organization_id=o.id
               WHERE m.user_id=? ORDER BY o.name""",
            (user["id"],),
        ).fetchall()
    return [_payload(row) for row in rows]


@router.get("/{public_id}/members")
def members(public_id: str, user: sqlite3.Row = Depends(_current_user)) -> list[dict]:
    public_id = _validate_org_id(public_id)
    with _db() as db:
        actor = _membership(db, public_id, int(user["id"]))
        if actor["role"] not in {"owner", "admin"}:
            raise HTTPException(status_code=403, detail="Administrator access required")
        rows = db.execute(
            """SELECT username,member_number,role,status,created_at,removed_at
               FROM organization_members WHERE organization_id=?
               ORDER BY created_at""",
            (actor["organization_id"],),
        ).fetchall()
    return [
        {
            **dict(row),
            "member_id": _member_id(public_id, row["member_number"]),
        }
        for row in rows
    ]


@router.delete("/{public_id}/members/{member_number}", status_code=204)
def remove_member(
    public_id: str,
    member_number: str,
    response: Response,
    user: sqlite3.Row = Depends(_current_user),
) -> Response:
    public_id = _validate_org_id(public_id)
    if not _MEMBER_RE.fullmatch(member_number):
        raise HTTPException(status_code=422, detail="Member number must be four digits")
    with _db() as db:
        actor = _membership(db, public_id, int(user["id"]))
        if actor["role"] not in {"owner", "admin"}:
            raise HTTPException(status_code=403, detail="Administrator access required")
        target = db.execute(
            """SELECT user_id,role,status,username FROM organization_members
               WHERE organization_id=? AND member_number=?""",
            (actor["organization_id"], member_number),
        ).fetchone()
        if not target or target["status"] != "active":
            raise HTTPException(status_code=404, detail="Active member not found")
        if target["role"] == "owner" and actor["role"] != "owner":
            raise HTTPException(status_code=403, detail="Only an owner can remove an owner")
        if target["role"] == "owner":
            owners = db.execute(
                """SELECT COUNT(*) FROM organization_members
                   WHERE organization_id=? AND role='owner' AND status='active'""",
                (actor["organization_id"],),
            ).fetchone()[0]
            if int(owners) <= 1:
                raise HTTPException(
                    status_code=409,
                    detail="Transfer ownership before removing the final owner",
                )
        now = _now()
        db.execute(
            """UPDATE organization_members
               SET status='revoked',removed_at=?,updated_at=?
               WHERE organization_id=? AND user_id=?""",
            (now, now, actor["organization_id"], target["user_id"]),
        )
        db.execute("DELETE FROM sessions WHERE user_id=?", (target["user_id"],))
        _audit(
            db,
            int(actor["organization_id"]),
            "member.revoked",
            int(user["id"]),
            int(target["user_id"]),
            f"member={member_number};username={target['username']}",
        )
        db.commit()
    response.status_code = 204
    return response


@router.post("/{public_id}/transfer-ownership")
def transfer_ownership(
    public_id: str,
    body: OwnershipTransfer,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    public_id = _validate_org_id(public_id)
    if not _MEMBER_RE.fullmatch(body.member_number):
        raise HTTPException(status_code=422, detail="Member number must be four digits")
    with _db() as db:
        actor = _membership(db, public_id, int(user["id"]))
        if actor["role"] != "owner":
            raise HTTPException(status_code=403, detail="Owner access required")
        target = db.execute(
            """SELECT user_id,username,member_number FROM organization_members
               WHERE organization_id=? AND member_number=? AND status='active'""",
            (actor["organization_id"], body.member_number),
        ).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="Active member not found")
        if int(target["user_id"]) == int(user["id"]):
            raise HTTPException(status_code=409, detail="Choose another active member")
        now = _now()
        db.execute(
            """UPDATE organization_members SET role='admin',updated_at=?
               WHERE organization_id=? AND user_id=?""",
            (now, actor["organization_id"], user["id"]),
        )
        db.execute(
            """UPDATE organization_members SET role='owner',updated_at=?
               WHERE organization_id=? AND user_id=?""",
            (now, actor["organization_id"], target["user_id"]),
        )
        db.execute(
            "UPDATE organizations SET owner_id=?,updated_at=? WHERE id=?",
            (target["user_id"], now, actor["organization_id"]),
        )
        _audit(
            db,
            int(actor["organization_id"]),
            "organization.ownership_transferred",
            int(user["id"]),
            int(target["user_id"]),
            f"member={body.member_number};username={target['username']}",
        )
        db.commit()
    return {
        "organization_id": public_id,
        "owner_member_id": _member_id(public_id, target["member_number"]),
        "owner_username": target["username"],
        "previous_owner_role": "admin",
    }


@router.patch("/{public_id}/identifier")
def change_identifier(
    public_id: str,
    body: OrganizationIdentifierChange,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    current_id = _validate_org_id(public_id)
    new_id = _validate_org_id(body.organization_id)
    with _db() as db:
        actor = _membership(db, current_id, int(user["id"]))
        if actor["role"] != "owner":
            raise HTTPException(status_code=403, detail="Owner access required")
        if db.execute(
            "SELECT 1 FROM organizations WHERE public_id=? AND id<>?",
            (new_id, actor["organization_id"]),
        ).fetchone():
            raise HTTPException(status_code=409, detail="Organization ID is in use")
        db.execute(
            "UPDATE organizations SET public_id=?,updated_at=? WHERE id=?",
            (new_id, _now(), actor["organization_id"]),
        )
        _audit(
            db,
            int(actor["organization_id"]),
            "organization.identifier_changed",
            int(user["id"]),
            detail=f"old={current_id};new={new_id}",
        )
        db.commit()
    return {
        "previous_organization_id": current_id,
        "organization_id": new_id,
        "member_id": _member_id(new_id, actor["member_number"]),
    }
