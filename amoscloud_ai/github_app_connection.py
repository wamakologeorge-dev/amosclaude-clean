"""Create a verified short-lived GitHub App installation connection.

This module is intended for trusted Amosclaud workflows. It never prints an
installation token. In GitHub Actions it masks the token and writes it only to
the runner-managed ``GITHUB_OUTPUT`` file for the next bounded step.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from jose import jwt
from jose.exceptions import JWKError, JWSError

from .bot_contributor_profile import (
    CANONICAL_REPOSITORY,
    TECHNICAL_APP_NAME,
    _http_request,
    _positive_integer,
    _private_key,
    _value,
)

GitHubRequest = Callable[
    [str, str, Mapping[str, str], Mapping[str, object] | None],
    tuple[int, Mapping[str, object]],
]


class GitHubAppConnectionError(RuntimeError):
    """A safe, non-secret GitHub App connection failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class InstallationConnection:
    token: str
    app_slug: str
    bot_login: str
    bot_user_id: str
    repository: str

    @property
    def actor_name(self) -> str:
        return TECHNICAL_APP_NAME

    @property
    def actor_email(self) -> str:
        return f"{self.bot_user_id}+{self.bot_login}@users.noreply.github.com"

    def public_evidence(self) -> dict[str, object]:
        return {
            "schema": "amosclaud.github-app-connection.v1",
            "status": "CONNECTED",
            "app_slug": self.app_slug,
            "bot_login": self.bot_login,
            "bot_user_id": self.bot_user_id,
            "repository": self.repository,
            "actor_name": self.actor_name,
            "actor_email": self.actor_email,
            "sensitive_value_disclosed": False,
        }


def connect_installation(
    *,
    repository: str,
    environment: Mapping[str, str] | None = None,
    request: GitHubRequest | None = None,
) -> InstallationConnection:
    """Authenticate the App and verify its installation can access *repository*."""

    env = os.environ if environment is None else environment
    app_id = _positive_integer(env, "GITHUB_APP_ID")
    installation_id = _positive_integer(
        env,
        "GITHUB_APP_INSTALLATION_ID",
        "AMOSCLAUD_GITHUB_APP_INSTALLATION_ID",
    )
    configured_slug = _value(env, "GITHUB_APP_SLUG")
    configured_bot_user_id = _positive_integer(env, "GITHUB_APP_BOT_USER_ID")
    private_key = _private_key(env)
    if not repository or "/" not in repository:
        raise GitHubAppConnectionError("REPOSITORY_INVALID")
    if not app_id or not installation_id or not private_key:
        raise GitHubAppConnectionError("CONFIGURATION_INCOMPLETE")

    now = int(time.time())
    try:
        app_jwt = jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": app_id},
            private_key,
            algorithm="RS256",
        )
    except (JWKError, JWSError, TypeError, ValueError) as exc:
        raise GitHubAppConnectionError("PRIVATE_KEY_INVALID") from exc

    requester = request or _http_request
    app_headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {app_jwt}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    status, app = requester("GET", "https://api.github.com/app", app_headers, None)
    if status != 200:
        raise GitHubAppConnectionError("APP_AUTHENTICATION_FAILED")
    app_slug = str(app.get("slug") or "").strip()
    if not app_slug:
        raise GitHubAppConnectionError("APP_SLUG_MISSING")
    if configured_slug and configured_slug != app_slug:
        raise GitHubAppConnectionError("APP_SLUG_MISMATCH")

    status, token_payload = requester(
        "POST",
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        app_headers,
        {},
    )
    token = str(token_payload.get("token") or "")
    if status != 201 or not token:
        raise GitHubAppConnectionError("INSTALLATION_AUTHENTICATION_FAILED")

    installation_headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    status, repository_payload = requester(
        "GET",
        f"https://api.github.com/repos/{repository}",
        installation_headers,
        None,
    )
    if status != 200 or str(repository_payload.get("full_name") or "") != repository:
        raise GitHubAppConnectionError("REPOSITORY_NOT_ACCESSIBLE")

    bot_login = f"{app_slug}[bot]"
    status, bot_user = requester(
        "GET",
        f"https://api.github.com/users/{quote(bot_login, safe='')}",
        installation_headers,
        None,
    )
    bot_user_id = str(bot_user.get("id") or "")
    if status != 200 or not bot_user_id.isdigit() or int(bot_user_id) <= 0:
        raise GitHubAppConnectionError("BOT_IDENTITY_NOT_ACCESSIBLE")
    if configured_bot_user_id and configured_bot_user_id != bot_user_id:
        raise GitHubAppConnectionError("BOT_USER_ID_MISMATCH")

    return InstallationConnection(
        token=token,
        app_slug=app_slug,
        bot_login=bot_login,
        bot_user_id=bot_user_id,
        repository=repository,
    )


def write_github_outputs(connection: InstallationConnection, output_path: Path) -> None:
    """Mask the installation token and publish bounded step outputs."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"::add-mask::{connection.token}")
    with output_path.open("a", encoding="utf-8") as output:
        output.write(f"token={connection.token}\n")
        output.write(f"actor_name={connection.actor_name}\n")
        output.write(f"actor_email={connection.actor_email}\n")
        output.write(f"bot_login={connection.bot_login}\n")
        output.write(f"app_slug={connection.app_slug}\n")
        output.write("connected=true\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository",
        default=os.getenv("GITHUB_REPOSITORY", CANONICAL_REPOSITORY),
    )
    parser.add_argument(
        "--github-output",
        default=os.getenv("GITHUB_OUTPUT", ""),
        help="Runner-managed output file. Required for workflow token handoff.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        connection = connect_installation(repository=args.repository)
    except GitHubAppConnectionError as exc:
        print(
            json.dumps(
                {
                    "schema": "amosclaud.github-app-connection.v1",
                    "status": "BLOCKED",
                    "failure_code": exc.code,
                    "sensitive_value_disclosed": False,
                },
                sort_keys=True,
            )
        )
        return 1

    if not args.github_output:
        print(
            json.dumps(
                {
                    "schema": "amosclaud.github-app-connection.v1",
                    "status": "BLOCKED",
                    "failure_code": "GITHUB_OUTPUT_MISSING",
                    "sensitive_value_disclosed": False,
                },
                sort_keys=True,
            )
        )
        return 1

    write_github_outputs(connection, Path(args.github_output))
    print(json.dumps(connection.public_evidence(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
