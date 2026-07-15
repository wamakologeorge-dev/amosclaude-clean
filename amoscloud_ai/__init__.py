"""Amosclaud AI - Self-hosted development and deployment platform."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def _configure_persistent_auth_storage() -> None:
    """Choose durable authentication storage before auth routes are imported.

    Production hosts commonly replace the application filesystem on every
    deployment. When a persistent ``/var/data`` volume is available, keep the
    account, session, and passkey database there so users are not recreated
    after each release. ``AUTH_DB_PATH`` always overrides this default.
    """
    if os.getenv("AUTH_DB_PATH"):
        return

    persistent_root = Path(os.getenv("AMOSCLAUD_DATA_DIR", "/var/data/amosclaud"))
    if not Path("/var/data").exists():
        return

    target = persistent_root / "auth.db"
    legacy = Path("data/auth.db")
    persistent_root.mkdir(parents=True, exist_ok=True)

    # Preserve an existing database during the first deployment that enables
    # the persistent disk. Never overwrite a database already on the disk.
    if not target.exists() and legacy.exists():
        shutil.copy2(legacy, target)

    os.environ["AUTH_DB_PATH"] = str(target)


_configure_persistent_auth_storage()

__version__ = "1.0.1"
__author__ = "Amosclaud Team"
__email__ = "support@amosclaud.com"
