"""Amosclaud Autonomous platform package.

``amoscloud_ai`` is retained temporarily as a compatibility import namespace so
existing deployments and extensions do not break. It is not the product name.
All user-visible branding, runtime identity, service labels, and new APIs must
use ``Amosclaud`` or ``Amosclaud Autonomous``.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from dotenv import load_dotenv

PRODUCT_NAME = "Amosclaud"
RUNTIME_NAME = "Amosclaud Autonomous"
LEGACY_IMPORT_NAMESPACE = "amoscloud_ai"
CANONICAL_AUTONOMOUS_PATH = "/autonomous"


def _configure_persistent_auth_storage() -> None:
    """Choose durable authentication storage before auth routes are imported.

    Production hosts commonly replace the application filesystem on every
    deployment. When a persistent ``/var/data`` volume is available, keep the
    account, session, and passkey database there so users are not recreated
    after each release. ``AUTH_DB_PATH`` always overrides this default.
    """
    # Package initialization happens before the platform application imports,
    # so load .env here before deciding whether the caller supplied an override.
    load_dotenv()
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

# Register the single operator and the project/issue/result routes on the shared
# task router before the FastAPI application mounts that router.
from amoscloud_ai import operator as _operator  # noqa: E402,F401
from amoscloud_ai import project_platform as _project_platform  # noqa: E402,F401

__all__ = [
    "CANONICAL_AUTONOMOUS_PATH",
    "LEGACY_IMPORT_NAMESPACE",
    "PRODUCT_NAME",
    "RUNTIME_NAME",
    "__version__",
]
