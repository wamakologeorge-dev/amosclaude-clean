"""Administrator bootstrap policy for Amosclaud.

Password and email bootstrap remain available for normal administrators. The
platform-owner path is intentionally different: it trusts only a verified GitHub
OAuth identity that matches the configured account and still controls the
configured source repository.
"""

from __future__ import annotations

import os

DEFAULT_ADMIN_EMAILS = (
    "georgemakulu@amosclaud.com",
    "wamakologeorge@gmail.com",
)
DEFAULT_ADMIN_GITHUB_IDS = ("271083488",)
DEFAULT_ADMIN_GITHUB_LOGINS = ("wamakologeorge-dev",)
DEFAULT_ADMIN_GITHUB_REPOSITORY = "wamakologeorge-dev/amosclaude-clean"
DEFAULT_ADMIN_GITHUB_EMAIL = "wamakologeorge@gmail.com"


def _configured_values(name: str, defaults: tuple[str, ...]) -> set[str]:
    raw = os.getenv(name)
    values = raw.split(",") if raw is not None else defaults
    return {value.strip().lower() for value in values if value.strip()}


def configured_admin_emails() -> set[str]:
    return _configured_values("AMOSCLAUD_ADMIN_EMAILS", DEFAULT_ADMIN_EMAILS)


def configured_admin_github_ids() -> set[str]:
    return _configured_values(
        "AMOSCLAUD_ADMIN_GITHUB_IDS",
        DEFAULT_ADMIN_GITHUB_IDS,
    )


def configured_admin_github_logins() -> set[str]:
    return _configured_values(
        "AMOSCLAUD_ADMIN_GITHUB_LOGINS",
        DEFAULT_ADMIN_GITHUB_LOGINS,
    )


def configured_admin_github_repository() -> str:
    return os.getenv(
        "AMOSCLAUD_ADMIN_GITHUB_REPOSITORY",
        DEFAULT_ADMIN_GITHUB_REPOSITORY,
    ).strip()


def configured_admin_github_email() -> str:
    return os.getenv(
        "AMOSCLAUD_ADMIN_GITHUB_EMAIL",
        DEFAULT_ADMIN_GITHUB_EMAIL,
    ).strip().lower()


def is_configured_github_admin(github_id: str, login: str) -> bool:
    return (
        github_id.strip().lower() in configured_admin_github_ids()
        and login.strip().lower() in configured_admin_github_logins()
    )


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
