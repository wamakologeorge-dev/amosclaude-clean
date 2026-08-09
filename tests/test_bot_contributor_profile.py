from __future__ import annotations

import json

from amoscloud_ai.bot_contributor_profile import build_profile


def test_unconfigured_profile_is_truthful_and_non_secret() -> None:
    profile = build_profile({})

    assert profile["display_name"] == "Amosclaud Bot"
    assert profile["bot_login"] == "amosclaud-platform[bot]"
    assert profile["readiness"]["verification_level"] == "UNCONFIGURED"
    assert profile["readiness"]["fully_ready"] is False
    assert profile["commit_identity"]["email"] is None


def test_ready_profile_builds_the_github_bot_commit_identity() -> None:
    profile = build_profile(
        {
            "GITHUB_APP_SLUG": "amosclaud-bot",
            "GITHUB_APP_ID": "12345",
            "GITHUB_APP_PRIVATE_KEY": "private-key-material",
            "GITHUB_APP_INSTALLATION_ID": "67890",
            "GITHUB_APP_WEBHOOK_SECRET": "webhook-secret",
            "GITHUB_APP_BOT_USER_ID": "24680",
        }
    )

    assert profile["bot_login"] == "amosclaud-bot[bot]"
    assert profile["commit_identity"]["name"] == "Amosclaud Bot"
    assert (
        profile["commit_identity"]["email"]
        == "24680+amosclaud-bot[bot]@users.noreply.github.com"
    )
    assert profile["readiness"]["verification_level"] == "READY"
    assert profile["readiness"]["fully_ready"] is True

    serialized = json.dumps(profile)
    assert "private-key-material" not in serialized
    assert "webhook-secret" not in serialized


def test_partial_profile_lists_only_missing_configuration_names() -> None:
    profile = build_profile(
        {
            "GITHUB_APP_SLUG": "amosclaud-bot",
            "GITHUB_APP_ID": "12345",
            "GITHUB_APP_PRIVATE_KEY_PATH": "/run/secrets/github-app.pem",
        }
    )

    readiness = profile["readiness"]
    assert readiness["verification_level"] == "PARTIAL"
    assert readiness["contributor_ready"] is False
    assert readiness["webhook_ready"] is False
    assert "installation_id_configured" in readiness["missing_configuration"]
    assert "webhook_secret_configured" in readiness["missing_configuration"]
    assert "/run/secrets/github-app.pem" not in json.dumps(profile)
