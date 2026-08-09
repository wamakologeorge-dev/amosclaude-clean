from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from amoscloud_ai.github_app_connection import (
    GitHubAppConnectionError,
    connect_installation,
    write_github_outputs,
)


def environment() -> dict[str, str]:
    return {
        "GITHUB_APP_ID": "12345",
        "GITHUB_APP_INSTALLATION_ID": "67890",
        "GITHUB_APP_PRIVATE_KEY": "private-key-material",
        "GITHUB_APP_SLUG": "amosclaud-bot",
        "GITHUB_APP_BOT_USER_ID": "24680",
    }


def test_connection_verifies_app_installation_repository_and_bot() -> None:
    calls: list[tuple[str, str, str]] = []

    def request(method, url, headers, payload):
        calls.append((method, url, headers.get("Authorization", "")))
        if url == "https://api.github.com/app":
            return 200, {"slug": "amosclaud-bot"}
        if url.endswith("/app/installations/67890/access_tokens"):
            return 201, {"token": "installation-token"}
        if url.endswith("/repos/owner/repo"):
            assert headers["Authorization"] == "Bearer installation-token"
            return 200, {"full_name": "owner/repo"}
        if url.endswith("/users/amosclaud-bot%5Bbot%5D"):
            assert headers["Authorization"] == "Bearer installation-token"
            return 200, {"id": 24680}
        raise AssertionError((method, url, payload))

    with patch(
        "amoscloud_ai.github_app_connection.jwt.encode",
        return_value="signed-app-jwt",
    ):
        connection = connect_installation(
            repository="owner/repo",
            environment=environment(),
            request=request,
        )

    assert connection.token == "installation-token"
    assert connection.bot_login == "amosclaud-bot[bot]"
    assert connection.actor_name == "Amosclaud Bot"
    assert connection.actor_email == "24680+amosclaud-bot[bot]@users.noreply.github.com"
    assert calls[0][2] == "Bearer signed-app-jwt"
    assert "installation-token" not in str(connection.public_evidence())


def test_connection_rejects_repository_without_installation_access() -> None:
    def request(method, url, headers, payload):
        if url == "https://api.github.com/app":
            return 200, {"slug": "amosclaud-bot"}
        if url.endswith("/access_tokens"):
            return 201, {"token": "installation-token"}
        if url.endswith("/repos/owner/repo"):
            return 404, {}
        raise AssertionError(url)

    with (
        patch(
            "amoscloud_ai.github_app_connection.jwt.encode",
            return_value="signed-app-jwt",
        ),
        pytest.raises(GitHubAppConnectionError) as exc_info,
    ):
        connect_installation(
            repository="owner/repo",
            environment=environment(),
            request=request,
        )

    assert exc_info.value.code == "REPOSITORY_NOT_ACCESSIBLE"


def test_connection_rejects_bot_identity_mismatch() -> None:
    def request(method, url, headers, payload):
        if url == "https://api.github.com/app":
            return 200, {"slug": "amosclaud-bot"}
        if url.endswith("/access_tokens"):
            return 201, {"token": "installation-token"}
        if url.endswith("/repos/owner/repo"):
            return 200, {"full_name": "owner/repo"}
        if "/users/" in url:
            return 200, {"id": 99999}
        raise AssertionError(url)

    with (
        patch(
            "amoscloud_ai.github_app_connection.jwt.encode",
            return_value="signed-app-jwt",
        ),
        pytest.raises(GitHubAppConnectionError) as exc_info,
    ):
        connect_installation(
            repository="owner/repo",
            environment=environment(),
            request=request,
        )

    assert exc_info.value.code == "BOT_USER_ID_MISMATCH"


def test_workflow_output_contains_masked_handoff_and_nonsecret_identity(
    tmp_path: Path,
    capsys,
) -> None:
    connection = type(
        "Connection",
        (),
        {
            "token": "installation-token",
            "actor_name": "Amosclaud Bot",
            "actor_email": "24680+amosclaud-bot[bot]@users.noreply.github.com",
            "bot_login": "amosclaud-bot[bot]",
            "app_slug": "amosclaud-bot",
        },
    )()
    output = tmp_path / "github-output.txt"

    write_github_outputs(connection, output)

    captured = capsys.readouterr().out
    assert "::add-mask::installation-token" in captured
    content = output.read_text(encoding="utf-8")
    assert "token=installation-token" in content
    assert "actor_name=Amosclaud Bot" in content
    assert "connected=true" in content
