from __future__ import annotations

import os
import re
from dataclasses import dataclass

from .bot import AmosclaudBot

READ_ONLY_COMMANDS = frozenset({"help", "inspect", "review", "status", "verify"})

# These phrases indicate a disclosure risk even when the requested operation is
# read-only. They deliberately exclude broad engineering words such as
# "deployment" and "authentication", which are safe to inspect publicly.
EXPLICIT_PRIVATE_HINTS = (
    "vulnerability",
    "secret",
    "credential",
    "token",
    "password",
    "incident",
    "private",
    "confidential",
    "customer data",
    "personal data",
)

# Write requests involving these areas require the protected owner-only route.
WRITE_SENSITIVE_HINTS = (
    "production",
    "deploy",
    "deployment",
    "security",
    "authentication",
    "authorization",
    "infrastructure",
)


@dataclass(frozen=True)
class PrivacyRoute:
    private: bool
    destination: str | None = None
    issue_number: int | None = None
    configured: bool = False


def _contains_hint(text: str, hint: str) -> bool:
    """Match whole words/phrases so terms such as ``tokenizer`` stay public."""
    if " " in hint:
        return hint in text
    return re.search(rf"(?<![a-z0-9_]){re.escape(hint)}(?![a-z0-9_])", text) is not None


def requires_private_work(text: str, command: str | None = None) -> bool:
    """Return whether a task must leave the public issue-processing path.

    Read-only inspection, review, and verification may discuss ordinary
    deployment or authentication code publicly. Explicit disclosure risks still
    fail closed. Write requests retain the stricter sensitive-operation policy.
    """
    lowered = " ".join((text or "").strip().lower().split())
    normalized_command = (command or "").strip().lower()

    if any(_contains_hint(lowered, hint) for hint in EXPLICIT_PRIVATE_HINTS):
        return True
    if normalized_command in READ_ONLY_COMMANDS:
        return False
    return any(_contains_hint(lowered, hint) for hint in WRITE_SENSITIVE_HINTS)


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
