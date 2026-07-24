"""Administrator bootstrap policy for Amosclaud.

Administrator rights are granted only after the normal email-verification flow.
The first registered account is not automatically privileged unless a self-hosted
operator explicitly enables that legacy bootstrap mode.
"""

from __future__ import annotations

import os

DEFAULT_ADMIN_EMAILS = (
    "georgemakulu@amosclaud.com",
    "wamakologeorge@gmail.com",
)


def configured_admin_emails() -> set[str]:
    raw = os.getenv("AMOSCLAUD_ADMIN_EMAILS")
    values = raw.split(",") if raw is not None else DEFAULT_ADMIN_EMAILS
    return {value.strip().lower() for value in values if value.strip()}


def first_user_bootstrap_enabled() -> bool:
    return os.getenv("AMOSCLAUD_ALLOW_FIRST_USER_ADMIN", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def should_grant_admin(email: str, *, is_first_user: bool) -> bool:
    normalized = email.strip().lower()
    if normalized in configured_admin_emails():
        return True
    return is_first_user and first_user_bootstrap_enabled()
