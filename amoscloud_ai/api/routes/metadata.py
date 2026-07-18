from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from amoscloud_ai.Amosclaud import AmosclaudDashboard
from amoscloud_ai.api.routes.admin import _admin_user

router = APIRouter(prefix="/metadata", tags=["amosclaud-metadata"])


@router.get("")
def platform_metadata(admin: sqlite3.Row = Depends(_admin_user)) -> dict:
    """Return a redacted platform metadata snapshot for administrators."""
    del admin
    return AmosclaudDashboard().snapshot()
