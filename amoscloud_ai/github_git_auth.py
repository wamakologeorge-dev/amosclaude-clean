"""Ephemeral GitHub authentication for Git commands.

The credential is supplied through process-local Git configuration environment
variables. It is never written to `.git/config`, a remote URL, or the project
workspace mounted into a user container.
"""

from __future__ import annotations

import base64
from contextlib import contextmanager
from typing import Iterator

from git import Repo


def git_auth_environment(token: str) -> dict[str, str]:
    credential = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraHeader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {credential}",
        "GIT_TERMINAL_PROMPT": "0",
    }


@contextmanager
def authenticated_git(repo: Repo, token: str) -> Iterator[None]:
    """Apply one process-local GitHub Authorization header for this operation."""

    with repo.git.custom_environment(**git_auth_environment(token)):
        yield
