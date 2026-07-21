from __future__ import annotations

import os
from dataclasses import dataclass

from .bot import AmosclaudBot

PRIVATE_HINTS = (
    "production",
    "deploy",
    "deployment",
    "security",
    "vulnerability",
    "secret",
    "credential",
    "token",
    "password",
    "authentication",
    "authorization",
    "infrastructure",
    "incident",
    "private",
    "confidential",
    "customer data",
    "personal data",
)


@dataclass(frozen=True)
class PrivacyRoute:
    private: bool
    destination: str | None = None
    issue_number: int | None = None
    configured: bool = False


def requires_private_work(text: str) -> bool:
    """Return True when a task should not create detailed public process issues."""
    lowered = " ".join((text or "").strip().lower().split())
    return any(hint in lowered for hint in PRIVATE_HINTS)


def route_private_work(*, source_bot: AmosclaudBot, title: str, body: str) -> PrivacyRoute:
    """Route serious work to an optional owner-controlled private repository.

    A public repository cannot make an individual Issue private. The native bot therefore
    never publishes the supplied private body back to the public repository. When
    AMOSCLAUD_PRIVATE_REPOSITORY and AMOSCLAUD_PRIVATE_TOKEN are configured, it creates
    the detailed issue in that private repository. Otherwise it fails closed and leaves
    only a redacted public notice to avoid accidental disclosure.
    """
    private_repo = os.getenv("AMOSCLAUD_PRIVATE_REPOSITORY", "").strip()
    private_token = os.getenv("AMOSCLAUD_PRIVATE_TOKEN", "").strip()
    if not private_repo or not private_token:
        return PrivacyRoute(private=True, configured=False)

    private_bot = AmosclaudBot(repository=private_repo, token=private_token)
    created = private_bot._request(
        "POST",
        f"/repos/{private_repo}/issues",
        {"title": title, "body": body},
    )
    number = created.get("number") if isinstance(created, dict) else None
    if not isinstance(number, int):
        raise RuntimeError("GitHub did not return a private work issue number")
    return PrivacyRoute(
        private=True,
        destination=private_repo,
        issue_number=number,
        configured=True,
    )
