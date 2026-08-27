"""Credential lookup for salted Amosclaud Authority secrets.

PBKDF2 hashes use a random salt, so a presented credential cannot be hashed
again and compared directly in SQL. The stable public prefix narrows the
candidate set; the stored PBKDF2 value is then checked in constant time by the
Authority module's verifier. Legacy SHA-256 rows are upgraded after a
successful authentication.
"""

from __future__ import annotations

from typing import Any


def install(authority) -> None:
    """Install the salted-hash-aware credential verifier on an Authority module."""

    def _matching_row(db, *, secret: str, table: str, join: str, owner_join: str):
        prefix = secret[:18]
        rows = db.execute(
            f"""SELECT {join}.*,u.name,u.email,u.is_admin,u.provider
                FROM {table} {join}
                JOIN users u ON u.id={owner_join}
                WHERE {join}.prefix=? AND {join}.revoked_at IS NULL""",
            (prefix,),
        ).fetchall()
        for row in rows:
            valid, needs_upgrade = authority._verify_secret(secret, row["secret_hash"])
            if valid:
                return row, needs_upgrade
        return None, False

    def authenticate_credential(
        raw: str | None, *, workspace_id: str | None = None
    ) -> dict[str, Any] | None:
        secret = str(raw or "").strip()
        if not secret:
            return None

        now = authority._now()
        with authority.auth._connect() as db:
            authority.ensure_schema(db)

            if secret.startswith(tuple(authority._PREFIXES.values())):
                row, needs_upgrade = _matching_row(
                    db,
                    secret=secret,
                    table="amosclaud_credentials",
                    join="c",
                    owner_join="c.owner_user_id",
                )
                if not row or not authority._active(row, now):
                    return None
                used_at = authority._iso(now)
                if needs_upgrade:
                    db.execute(
                        "UPDATE amosclaud_credentials SET secret_hash=? WHERE id=?",
                        (authority._hash_secret(secret), row["id"]),
                    )
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
                    "scopes": authority._loads_scopes(row["scopes_json"]),
                    "workspace_id": None,
                    "expires_at": row["expires_at"],
                }

            if not secret.startswith("amos_ext_"):
                return None
            row, needs_upgrade = _matching_row(
                db,
                secret=secret,
                table="amosclaud_workspace_grants",
                join="g",
                owner_join="g.created_by_user_id",
            )
            if not row or not authority._active(row, now):
                return None
            if workspace_id is None or str(workspace_id).strip() != row["workspace_id"]:
                return None
            used_at = authority._iso(now)
            if needs_upgrade:
                db.execute(
                    "UPDATE amosclaud_workspace_grants SET secret_hash=? WHERE id=?",
                    (authority._hash_secret(secret), row["id"]),
                )
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
                "scopes": authority._loads_scopes(row["scopes_json"]),
                "workspace_id": row["workspace_id"],
                "expires_at": row["expires_at"],
            }

    def verify_credential(
        raw: str | None,
        *,
        required_scope: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any] | None:
        principal = authenticate_credential(raw, workspace_id=workspace_id)
        if principal is None:
            return None
        principal = dict(principal)
        principal["required_scope"] = required_scope
        principal["scope_granted"] = authority.scope_allowed(principal, required_scope)
        return principal

    authority.authenticate_credential = authenticate_credential
    authority.verify_credential = verify_credential
