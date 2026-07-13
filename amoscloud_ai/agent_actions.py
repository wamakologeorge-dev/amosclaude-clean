"""Deterministic first-party actions executed by the Amosclaud chat agent.

These actions run only for explicit commands and return only after the platform
operation has succeeded. Normal conversational requests continue to the selected
AI provider.
"""

from __future__ import annotations

import re

from fastapi import HTTPException

_REPOSITORY_CREATE_RE = re.compile(
    r"^\s*(?:please\s+)?(?:create|make|start|initialize)\s+"
    r"(?:(?:a|an|new)\s+)?(?:amosclaud\s+)?(?:repository|repo)\s+"
    r"(?:(?:called|named|for)\s+)?[\"']?"
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]{0,99})[\"']?"
    r"(?:\s|$)",
    re.IGNORECASE,
)


def parse_repository_create_command(message: str) -> dict[str, object] | None:
    """Parse an explicit repository-creation command without guessing intent."""
    match = _REPOSITORY_CREATE_RE.search(message)
    if not match:
        return None
    lowered = message.lower()
    visibility = "public" if re.search(r"\bpublic\b", lowered) else "private"
    description_match = re.search(
        r"\bdescription\s*[:=-]?\s*[\"']?(?P<description>[^\"']{1,500})[\"']?\s*$",
        message,
        re.IGNORECASE,
    )
    description = description_match.group("description").strip() if description_match else "Created by the Amosclaud agent."
    return {
        "name": match.group("name"),
        "description": description,
        "visibility": visibility,
        "initialize_readme": True,
    }


def execute_repository_create(message: str, session_token: str | None):
    """Create a real native repository for the authenticated Amosclaud user."""
    command = parse_repository_create_command(message)
    if command is None:
        return None

    from amoscloud_ai.api.routes import auth, repositories

    user = auth.get_user_from_session(session_token)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in before asking Amosclaud to create a repository")

    body = repositories.RepositoryCreate(**command)
    return repositories.create_repository(body, user)
