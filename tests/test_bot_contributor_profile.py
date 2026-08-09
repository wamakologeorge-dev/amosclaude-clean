from __future__ import annotations

import json
from unittest.mock import patch

from amoscloud_ai.bot_contributor_profile import build_profile, verify_live_profile


def configured_environment() -> dict[str, str]:
    return {
        "GITHUB_APP_SLUG": "amosclaud-bot",
        "GITHUB_APP_ID": "12345",
        "GITHUB_APP_PRIVATE_KEY": "private-key-material",
        "GITHUB_APP_INSTALLATION_ID": "67890",
        "GITHUB_APP_WEBHOOK_SECRET": "webhook-secret",
        "GITHUB_APP_BOT_USER_ID": "24680",
    }


def test_public_profile_preserves_autonomous_identity_and_bot_attribution() -> None:
    profile = build_profile(configured_environment())

    assert profile["display_name"] == "Amosclaud Autonomous"
    assert "Amosclaud Autonomous" in profile["bio"]
    attribution = profile["github_attribution"]
    assert attribution["technical_name"] == "Amosclaud Bot"
    assert attribution["bot_login"] == "amosclaud-bot[bot]"
    assert attribution["commit_identity"]["name"] == "Amosclaud Bot"
    assert (
        attribution["commit_identity"]["email"]
        == "24680+amosclaud-bot[bot]@users.noreply.github.com"
    )


def test_unconfigured_profile_uses_canonical_bot_slug() -> None:
    profile = build_profile({})

    attribution = profile["github_attribution"]
    assert attribution["app_slug"] == "amosclaud-bot"
    assert attribution["bot_login"] == "amosclaud-bot[bot]"
    assert profile["configuration"]["identity_configuration_level"] == "INCOMPLETE"
    assert profile["verification"]["contributor_ready"] is False


def test_configuration_presence_never_claims_live_readiness_or_exposes_secrets() -> None:
    profile = build_profile(configured_environment())

    assert profile["configuration"]["identity_configuration_level"] == "IDENTITY_CONFIGURED"
    assert profile["configuration"]["configuration_presence_is_not_live_readiness"] is True
    assert profile["verification"]["verification_level"] == "NOT_RUN"
    assert profile["verification"]["contributor_ready"] is False
    assert profile["verification"]["fully_ready"] is False

    serialized = json.dumps(profile)
    assert "private-key-material" not in serialized
    assert "webhook-secret" not in serialized
    assert "67890" not in serialized
    assert "12345" not in serialized


def test_incomplete_public_profile_is_truthful() -> None:
    profile = build_profile({"GITHUB_APP_SLUG": "amosclaud-bot"})

    assert profile["display_name"] == "Amosclaud Autonomous"
    assert profile["github_attribution"]["bot_login"] == "amosclaud-bot[bot]"
    assert profile["configuration"]["identity_configuration_level"] == "INCOMPLETE"
    assert profile["github_attribution"]["commit_identity"]["email"] is None
    assert profile["verification"]["contributor_ready"] is False


def test_live_verification_authenticates_app_installation_repository_and_bot() -> None:
    calls: list[tuple[str, str, str]] = []

    def request(method, url, headers, payload):
        calls.append((method, url, headers.get("Authorization", "")))
        if url == "https://api.github.com/app":
            return 200, {"slug": "amosclaud-bot"}
        if url.endswith("/app/installations/67890/access_tokens"):
            return 201, {"token": "installation-token"}
        if url.endswith("/repos/wamakologeorge-dev/amosclaude-clean"):
            assert headers["Authorization"] == "Bearer installation-token"
            return 200, {"full_name": "wamakologeorge-dev/amosclaude-clean"}
        if url.endswith("/users/amosclaud-bot%5Bbot%5D"):
            assert headers["Authorization"] == "Bearer installation-token"
            return 200, {"id": 24680}
        raise AssertionError((method, url, payload))

    with patch(
        "amoscloud_ai.bot_contributor_profile.jwt.encode",
        return_value="signed-app-jwt",
    ):
        result = verify_live_profile(configured_environment(), request=request)

    assert result["verification_level"] == "LIVE_AUTH_VERIFIED"
    assert result["contributor_ready"] is True
    assert result["canonical_repository_accessible"] is True
    assert "webhook_configuration_present" not in result
    assert result["webhook_delivery_verified"] is False
    assert result["fully_ready"] is False
    assert result["remaining_verification"] == "SIGNED_WEBHOOK_DELIVERY_REQUIRED"
    assert calls[0][2] == "Bearer signed-app-jwt"

    serialized = json.dumps(result)
    assert "private-key-material" not in serialized
    assert "webhook-secret" not in serialized
    assert "installation-token" not in serialized
    assert "signed-app-jwt" not in serialized


def test_live_verification_rejects_failed_app_authentication() -> None:
    with patch(
        "amoscloud_ai.bot_contributor_profile.jwt.encode",
        return_value="signed-app-jwt",
    ):
        result = verify_live_profile(
            configured_environment(),
            request=lambda method, url, headers, payload: (401, {}),
        )

    assert result["verification_level"] == "FAILED"
    assert result["failure_code"] == "APP_AUTHENTICATION_FAILED"
    assert result["contributor_ready"] is False
    assert result["fully_ready"] is False
