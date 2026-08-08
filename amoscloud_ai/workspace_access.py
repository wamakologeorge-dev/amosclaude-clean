"""Production repository access policy for the Amosclaud platform owner.

Normal users still receive the repository role recorded by the native repository
service. A verified platform administrator may operate any native repository
through the production control plane, which prevents owner tools from failing
with a misleading ``Write access required`` response after an account migration
or repository import.

The policy is installed before the main application imports route modules so
all routes receive the same access function. It does not change public access,
make regular viewers writable, or bypass branch and verification controls.
"""

from __future__ import annotations

import sqlite3
from typing import Callable

from fastapi import HTTPException

from amoscloud_ai.api.routes import repositories

AccessFunction = Callable[[sqlite3.Connection, int, int], sqlite3.Row]


def _is_platform_admin(db: sqlite3.Connection, user_id: int) -> bool:
    row = db.execute(
        "SELECT is_admin FROM users WHERE id=?",
        (int(user_id),),
    ).fetchone()
    return bool(row and row["is_admin"])


def _administrator_repository(
    db: sqlite3.Connection,
    repository_id: int,
) -> sqlite3.Row:
    row = db.execute(
        """SELECT r.*, u.name AS owner_name, 'owner' AS role
           FROM repositories r
           JOIN users u ON u.id = r.owner_id
           WHERE r.id = ?""",
        (int(repository_id),),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Repository not found")
    return row


def install_admin_repository_access() -> None:
    """Install one idempotent production access function.

    The override is deliberately narrow: only a user whose persisted account
    has ``is_admin=1`` receives the owner-equivalent control-plane role. Every
    other user continues through the existing repository access policy.
    """

    current = repositories._access
    if getattr(current, "_amosclaud_admin_access", False):
        return

    original: AccessFunction = current

    def admin_aware_access(
        db: sqlite3.Connection,
        repository_id: int,
        user_id: int,
    ) -> sqlite3.Row:
        if _is_platform_admin(db, user_id):
            return _administrator_repository(db, repository_id)
        return original(db, repository_id, user_id)

    setattr(admin_aware_access, "_amosclaud_admin_access", True)
    setattr(admin_aware_access, "_amosclaud_original_access", original)
    repositories._access = admin_aware_access


__all__ = ["install_admin_repository_access"]
