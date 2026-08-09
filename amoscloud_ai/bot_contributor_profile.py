"""Non-secret contributor identity contract for the Amosclaud GitHub App.

The public profile is safe to expose to authenticated platform users. It never
returns private keys, webhook secrets, installation tokens, or environment
values. Readiness means the GitHub App can authenticate as an installation and
attribute repository work to its own bot identity.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence

DISPLAY_NAME = "Amosclaud Bot"
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


def _value(environment: Mapping[str, str], name: str) -> str:
    return str(environment.get(name, "")).strip()


def _any_configured(environment: Mapping[str, str], names: Sequence[str]) -> bool:
    return any(_value(environment, name) for name in names)


def build_profile(environment: Mapping[str, str] | None = None) -> dict[str, object]:
    """Return the public contributor profile and non-secret readiness evidence."""

    env = os.environ if environment is None else environment
    app_slug = _value(env, "GITHUB_APP_SLUG") or DEFAULT_APP_SLUG
    bot_login = f"{app_slug}[bot]"
    bot_user_id = _value(env, "GITHUB_APP_BOT_USER_ID")
    bot_user_id_valid = bot_user_id.isdigit() and int(bot_user_id) > 0

    checks = {
        "app_id_configured": bool(_value(env, "GITHUB_APP_ID")),
        "private_key_configured": _any_configured(
            env,
            (
                "GITHUB_APP_PRIVATE_KEY",
                "GITHUB_APP_PRIVATE_KEY_PATH",
                "AMOSCLAUD_GITHUB_APP_PRIVATE_KEY",
            ),
        ),
        "installation_id_configured": bool(
            _value(env, "GITHUB_APP_INSTALLATION_ID")
            or _value(env, "AMOSCLAUD_GITHUB_APP_INSTALLATION_ID")
        ),
        "webhook_secret_configured": bool(_value(env, "GITHUB_APP_WEBHOOK_SECRET")),
        "bot_user_id_configured": bot_user_id_valid,
    }

    contributor_ready = all(
        checks[name]
        for name in (
            "app_id_configured",
            "private_key_configured",
            "installation_id_configured",
            "bot_user_id_configured",
        )
    )
    webhook_ready = checks["webhook_secret_configured"]
    fully_ready = contributor_ready and webhook_ready

    missing_configuration = [name for name, configured in checks.items() if not configured]
    if fully_ready:
        verification_level = "READY"
    elif any(checks.values()):
        verification_level = "PARTIAL"
    else:
        verification_level = "UNCONFIGURED"

    commit_email = (
        f"{bot_user_id}+{bot_login}@users.noreply.github.com" if bot_user_id_valid else None
    )

    return {
        "schema": "amosclaud.github-contributor-profile.v1",
        "display_name": DISPLAY_NAME,
        "app_slug": app_slug,
        "bot_login": bot_login,
        "role": ROLE,
        "homepage": HOMEPAGE,
        "canonical_repository": CANONICAL_REPOSITORY,
        "bio": (
            "Amosclaud Bot is an autonomous software-engineering contributor that "
            "inspects repositories, prepares bounded repairs, runs verification, and "
            "publishes auditable GitHub evidence."
        ),
        "capabilities": list(CAPABILITIES),
        "commit_identity": {
            "name": DISPLAY_NAME,
            "email": commit_email,
            "ready": commit_email is not None,
        },
        "readiness": {
            "verification_level": verification_level,
            "contributor_ready": contributor_ready,
            "webhook_ready": webhook_ready,
            "fully_ready": fully_ready,
            "checks": checks,
            "missing_configuration": missing_configuration,
        },
        "safety": {
            "secrets_exposed": False,
            "direct_protected_branch_writes": False,
            "automatic_merge": False,
            "claim_requires_verification": True,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Exit non-zero unless contributor and webhook readiness are both verified.",
    )
    return parser


def _redact_profile_for_output(profile: Mapping[str, object]) -> dict[str, object]:
    """Return a logging-safe profile without secret-derived readiness details."""

    redacted = dict(profile)
    readiness = profile.get("readiness")
    if isinstance(readiness, Mapping):
        safe_readiness = dict(readiness)
        safe_readiness.pop("checks", None)
        safe_readiness.pop("missing_configuration", None)
        redacted["readiness"] = safe_readiness
    return redacted


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    profile = build_profile()
    print(json.dumps(_redact_profile_for_output(profile), indent=2, sort_keys=True))
    if args.require_ready and not profile["readiness"]["fully_ready"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
