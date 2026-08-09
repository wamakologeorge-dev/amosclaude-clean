"""Public identity and live verification for the Amosclaud GitHub App.

The public product identity remains ``Amosclaud Autonomous``. ``Amosclaud Bot``
is the technical GitHub App attribution used for commits and API actions. Public
profile output never reads or prints private keys, webhook secrets, installation
tokens, or secret-derived configuration details.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from urllib.parse import quote

import httpx
from jose import jwt
from jose.exceptions import JWKError, JWSError

PUBLIC_IDENTITY = "Amosclaud Autonomous"
TECHNICAL_APP_NAME = "Amosclaud Bot"
DEFAULT_APP_SLUG = "amosclaud-platform"
ROLE = "Autonomous software-engineering contributor"
HOMEPAGE = "https://www.amosclaud.com"
CANONICAL_REPOSITORY = "wamakologeorge-dev/amosclaude-clean"
CAPABILITIES = (
    "inspect repositories and workflow failures",
    "prepare bounded repair branches and pull requests",
    "run deterministic tests, quality checks, and security checks",
    "publish auditable comments, evidence, and status reports",
    "receive verified GitHub App webhook deliveries",
)
GitHubRequest = Callable[
    [str, str, Mapping[str, str], Mapping[str, object] | None],
    tuple[int, Mapping[str, object]],
]


def _value(environment: Mapping[str, str], name: str) -> str:
    return str(environment.get(name, "")).strip()


def _positive_integer(environment: Mapping[str, str], *names: str) -> str:
    for name in names:
        value = _value(environment, name)
        if value.isdigit() and int(value) > 0:
            return value
    return ""


def build_profile(environment: Mapping[str, str] | None = None) -> dict[str, object]:
    """Return public identity and non-secret technical attribution metadata."""

    env = os.environ if environment is None else environment
    app_slug = _value(env, "GITHUB_APP_SLUG") or DEFAULT_APP_SLUG
    bot_login = f"{app_slug}[bot]"
    app_id = _positive_integer(env, "GITHUB_APP_ID")
    installation_id = _positive_integer(
        env,
        "GITHUB_APP_INSTALLATION_ID",
        "AMOSCLAUD_GITHUB_APP_INSTALLATION_ID",
    )
    bot_user_id = _positive_integer(env, "GITHUB_APP_BOT_USER_ID")
    identity_configured = bool(app_id and installation_id and bot_user_id)
    commit_email = (
        f"{bot_user_id}+{bot_login}@users.noreply.github.com" if bot_user_id else None
    )

    return {
        "schema": "amosclaud.github-contributor-profile.v2",
        "display_name": PUBLIC_IDENTITY,
        "role": ROLE,
        "homepage": HOMEPAGE,
        "canonical_repository": CANONICAL_REPOSITORY,
        "bio": (
            "Amosclaud Autonomous is an autonomous software-engineering contributor "
            "that inspects repositories, prepares bounded repairs, runs verification, "
            "and publishes auditable GitHub evidence."
        ),
        "capabilities": list(CAPABILITIES),
        "github_attribution": {
            "technical_name": TECHNICAL_APP_NAME,
            "app_slug": app_slug,
            "bot_login": bot_login,
            "commit_identity": {
                "name": TECHNICAL_APP_NAME,
                "email": commit_email,
                "configured": commit_email is not None,
            },
        },
        "configuration": {
            "identity_configuration_level": (
                "IDENTITY_CONFIGURED" if identity_configured else "INCOMPLETE"
            ),
            "app_id_configured": bool(app_id),
            "installation_id_configured": bool(installation_id),
            "bot_user_id_configured": bool(bot_user_id),
            "protected_credentials_required_for_live_verification": True,
            "configuration_presence_is_not_live_readiness": True,
        },
        "verification": {
            "verification_level": "NOT_RUN",
            "contributor_ready": False,
            "webhook_delivery_verified": False,
            "fully_ready": False,
        },
        "safety": {
            "secrets_exposed": False,
            "direct_protected_branch_writes": False,
            "automatic_merge": False,
            "claim_requires_first_party_verification": True,
        },
    }


def _private_key(environment: Mapping[str, str]) -> str:
    for name in ("GITHUB_APP_PRIVATE_KEY", "AMOSCLAUD_GITHUB_APP_PRIVATE_KEY"):
        value = _value(environment, name)
        if value:
            return value.replace("\\n", "\n")

    path_value = _value(environment, "GITHUB_APP_PRIVATE_KEY_PATH")
    if not path_value:
        return ""
    try:
        path = Path(path_value).expanduser().resolve(strict=True)
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8")
    except (OSError, RuntimeError, UnicodeError):
        return ""


def _http_request(
    method: str,
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, object] | None,
) -> tuple[int, Mapping[str, object]]:
    try:
        with httpx.Client(timeout=15.0, follow_redirects=False) as client:
            response = client.request(method, url, headers=dict(headers), json=payload)
        data = response.json() if response.content else {}
        return response.status_code, data if isinstance(data, Mapping) else {}
    except (httpx.HTTPError, ValueError):
        return 0, {}


def _verification_failure(code: str) -> dict[str, object]:
    return {
        "schema": "amosclaud.github-contributor-live-verification.v1",
        "verification_level": "FAILED",
        "failure_code": code,
        "contributor_ready": False,
        "webhook_configuration_present": False,
        "webhook_delivery_verified": False,
        "fully_ready": False,
    }


def verify_live_profile(
    environment: Mapping[str, str] | None = None,
    *,
    request: GitHubRequest | None = None,
) -> dict[str, object]:
    """Authenticate as the App and installation without returning credentials."""

    env = os.environ if environment is None else environment
    app_slug = _value(env, "GITHUB_APP_SLUG") or DEFAULT_APP_SLUG
    app_id = _positive_integer(env, "GITHUB_APP_ID")
    installation_id = _positive_integer(
        env,
        "GITHUB_APP_INSTALLATION_ID",
        "AMOSCLAUD_GITHUB_APP_INSTALLATION_ID",
    )
    bot_user_id = _positive_integer(env, "GITHUB_APP_BOT_USER_ID")
    private_key = _private_key(env)
    webhook_secret_configured = bool(_value(env, "GITHUB_APP_WEBHOOK_SECRET"))
    if not all((app_id, installation_id, bot_user_id, private_key)):
        return _verification_failure("CONFIGURATION_INCOMPLETE")

    now = int(time.time())
    try:
        app_jwt = jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": app_id},
            private_key,
            algorithm="RS256",
        )
    except (JWKError, JWSError, TypeError, ValueError):
        return _verification_failure("PRIVATE_KEY_INVALID")

    requester = request or _http_request
    app_headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {app_jwt}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    status, app = requester("GET", "https://api.github.com/app", app_headers, None)
    if status != 200:
        return _verification_failure("APP_AUTHENTICATION_FAILED")
    verified_slug = str(app.get("slug") or "").strip()
    if verified_slug != app_slug:
        return _verification_failure("APP_SLUG_MISMATCH")

    status, token_payload = requester(
        "POST",
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        app_headers,
        {},
    )
    installation_token = str(token_payload.get("token") or "")
    if status != 201 or not installation_token:
        return _verification_failure("INSTALLATION_AUTHENTICATION_FAILED")

    installation_headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {installation_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    status, repository = requester(
        "GET",
        f"https://api.github.com/repos/{CANONICAL_REPOSITORY}",
        installation_headers,
        None,
    )
    if status != 200 or str(repository.get("full_name") or "") != CANONICAL_REPOSITORY:
        return _verification_failure("CANONICAL_REPOSITORY_NOT_ACCESSIBLE")

    bot_login = f"{verified_slug}[bot]"
    status, bot_user = requester(
        "GET",
        f"https://api.github.com/users/{quote(bot_login, safe='')}",
        installation_headers,
        None,
    )
    if status != 200 or str(bot_user.get("id") or "") != bot_user_id:
        return _verification_failure("BOT_USER_ID_MISMATCH")

    return {
        "schema": "amosclaud.github-contributor-live-verification.v1",
        "verification_level": "LIVE_AUTH_VERIFIED",
        "failure_code": None,
        "verified_app_slug": verified_slug,
        "verified_bot_login": bot_login,
        "canonical_repository_accessible": True,
        "contributor_ready": True,
        "webhook_configuration_present": webhook_secret_configured,
        "webhook_delivery_verified": False,
        "fully_ready": False,
        "remaining_verification": "SIGNED_WEBHOOK_DELIVERY_REQUIRED",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help=(
            "Authenticate as the GitHub App and installation. A signed webhook "
            "delivery remains a separate production verification."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.require_ready:
        verification = verify_live_profile()
        print(json.dumps(verification, indent=2, sort_keys=True))
        return 0 if verification["contributor_ready"] else 1

    print(json.dumps(build_profile(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
