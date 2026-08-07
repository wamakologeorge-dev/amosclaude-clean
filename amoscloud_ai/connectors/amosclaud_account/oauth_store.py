"""Durable OAuth client, consent, code, and token storage."""

from __future__ import annotations

import json
import secrets
import sqlite3

from fastapi import HTTPException
from mcp.server.auth.provider import AccessToken, TokenVerifier

from amoscloud_ai.api.routes import auth

from .oauth_config import (
    ACCESS_TOKEN_SECONDS,
    AUTHORIZATION_CODE_SECONDS,
    REFRESH_TOKEN_SECONDS,
    connector_resource_url,
    now,
    oauth_issuer_url,
    token_hash,
    valid_redirect_uri,
)


def connect() -> sqlite3.Connection:
    db = auth._connect()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS connector_oauth_clients (
            client_id TEXT PRIMARY KEY,
            client_name TEXT NOT NULL,
            redirect_uris_json TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS connector_oauth_consents (
            request_id_hash TEXT PRIMARY KEY,
            client_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            redirect_uri TEXT NOT NULL,
            state TEXT,
            scope TEXT NOT NULL,
            code_challenge TEXT NOT NULL,
            resource TEXT NOT NULL,
            expires_at INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS connector_oauth_codes (
            code_hash TEXT PRIMARY KEY,
            client_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            redirect_uri TEXT NOT NULL,
            scope TEXT NOT NULL,
            code_challenge TEXT NOT NULL,
            resource TEXT NOT NULL,
            expires_at INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS connector_oauth_tokens (
            access_token_hash TEXT PRIMARY KEY,
            refresh_token_hash TEXT NOT NULL UNIQUE,
            client_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            scope TEXT NOT NULL,
            resource TEXT NOT NULL,
            access_expires_at INTEGER NOT NULL,
            refresh_expires_at INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            last_used_at INTEGER,
            revoked_at INTEGER,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_connector_oauth_token_user
          ON connector_oauth_tokens(user_id, revoked_at, access_expires_at);
        CREATE INDEX IF NOT EXISTS idx_connector_oauth_refresh
          ON connector_oauth_tokens(refresh_token_hash, revoked_at, refresh_expires_at);
        """)
    db.commit()
    return db


def cleanup(db: sqlite3.Connection) -> None:
    current = now()
    db.execute("DELETE FROM connector_oauth_consents WHERE expires_at<=?", (current,))
    db.execute("DELETE FROM connector_oauth_codes WHERE expires_at<=?", (current,))
    db.execute(
        "DELETE FROM connector_oauth_tokens WHERE refresh_expires_at<=? OR "
        "(revoked_at IS NOT NULL AND revoked_at<=?)",
        (current, current - 7 * 24 * 60 * 60),
    )
    db.commit()


def client(db: sqlite3.Connection, client_id: str) -> sqlite3.Row:
    row = db.execute(
        "SELECT * FROM connector_oauth_clients WHERE client_id=?",
        (client_id.strip(),),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="Unknown OAuth client")
    return row


def registered_redirect(client_row: sqlite3.Row, redirect_uri: str) -> str:
    cleaned = valid_redirect_uri(redirect_uri)
    allowed = json.loads(client_row["redirect_uris_json"])
    if cleaned not in allowed:
        raise HTTPException(status_code=400, detail="OAuth redirect URI is not registered")
    return cleaned


def create_authorization_code(db: sqlite3.Connection, consent: sqlite3.Row) -> str:
    code = "amos_mcp_code_" + secrets.token_urlsafe(36)
    current = now()
    db.execute(
        """INSERT INTO connector_oauth_codes(
             code_hash,client_id,user_id,redirect_uri,scope,code_challenge,
             resource,expires_at,created_at
           ) VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            token_hash(code),
            consent["client_id"],
            int(consent["user_id"]),
            consent["redirect_uri"],
            consent["scope"],
            consent["code_challenge"],
            consent["resource"],
            current + AUTHORIZATION_CODE_SECONDS,
            current,
        ),
    )
    return code


def issue_tokens(
    db: sqlite3.Connection,
    *,
    client_id: str,
    user_id: int,
    scope: str,
    resource: str,
) -> dict[str, object]:
    current = now()
    access_token = "amos_mcp_at_" + secrets.token_urlsafe(48)
    refresh_token = "amos_mcp_rt_" + secrets.token_urlsafe(56)
    db.execute(
        """INSERT INTO connector_oauth_tokens(
             access_token_hash,refresh_token_hash,client_id,user_id,scope,resource,
             access_expires_at,refresh_expires_at,created_at
           ) VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            token_hash(access_token),
            token_hash(refresh_token),
            client_id,
            user_id,
            scope,
            resource,
            current + ACCESS_TOKEN_SECONDS,
            current + REFRESH_TOKEN_SECONDS,
            current,
        ),
    )
    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": ACCESS_TOKEN_SECONDS,
        "refresh_token": refresh_token,
        "scope": scope,
    }


class AmosclaudConnectorTokenVerifier(TokenVerifier):
    """Validate account connector bearer tokens and attach account claims."""

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token.startswith("amos_mcp_at_"):
            return None
        with connect() as db:
            cleanup(db)
            row = db.execute(
                """SELECT t.*,u.is_admin,u.email
                   FROM connector_oauth_tokens t
                   JOIN users u ON u.id=t.user_id
                   WHERE t.access_token_hash=? AND t.revoked_at IS NULL
                     AND t.access_expires_at>? AND t.resource=?""",
                (token_hash(token), now(), connector_resource_url()),
            ).fetchone()
            if not row:
                return None
            db.execute(
                "UPDATE connector_oauth_tokens SET last_used_at=? WHERE access_token_hash=?",
                (now(), row["access_token_hash"]),
            )
            db.commit()
        return AccessToken(
            token=token,
            client_id=str(row["client_id"]),
            scopes=str(row["scope"]).split(),
            expires_at=int(row["access_expires_at"]),
            resource=str(row["resource"]),
            subject=str(row["user_id"]),
            claims={
                "is_admin": bool(row["is_admin"]),
                "email": str(row["email"]),
                "iss": oauth_issuer_url(),
            },
        )
