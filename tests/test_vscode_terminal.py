from __future__ import annotations

import time

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from amoscloud_ai.api.routes import vscode_terminal


def _request(*, authorization: str = "", cookie: str = "") -> Request:
    headers = []
    if authorization:
        headers.append((b"authorization", authorization.encode()))
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "query_string": b"",
            "scheme": "https",
            "server": ("www.amosclaud.com", 443),
            "client": ("127.0.0.1", 1234),
        }
    )


def test_bearer_token_is_parsed_without_accepting_other_schemes():
    assert vscode_terminal._bearer_token(_request(authorization="Bearer user-key")) == "user-key"
    assert vscode_terminal._bearer_token(_request(authorization="Basic user-key")) == ""
    assert vscode_terminal._bearer_token(_request()) == ""


def test_terminal_user_accepts_per_user_autonomous_key(monkeypatch):
    expected = {"id": 42, "name": "George"}
    monkeypatch.setattr(vscode_terminal, "get_user_from_session", lambda _value: None)
    monkeypatch.setattr(
        vscode_terminal,
        "authenticate_autonomous_key",
        lambda value: expected if value == "user-key" else None,
    )

    user = vscode_terminal._user(_request(authorization="Bearer user-key"))

    assert user == expected


def test_terminal_user_rejects_missing_or_invalid_credentials(monkeypatch):
    monkeypatch.setattr(vscode_terminal, "get_user_from_session", lambda _value: None)
    monkeypatch.setattr(vscode_terminal, "authenticate_autonomous_key", lambda _value: None)

    with pytest.raises(HTTPException, match="per-user Amosclaud Autonomous key"):
        vscode_terminal._user(_request())


def test_terminal_ticket_is_single_use_and_user_scoped():
    token = "one-time-ticket"
    claims = {
        "repository_id": 7,
        "user_id": 42,
        "workspace_id": "workspace-7",
        "terminal_id": "term_12345678",
        "profile": "bash",
        "expires_at": int(time.time()) + 60,
    }
    with vscode_terminal._TICKET_LOCK:
        vscode_terminal._TICKETS.clear()
        vscode_terminal._TICKETS[token] = claims

    assert vscode_terminal._consume_ticket(token) == claims
    with pytest.raises(HTTPException, match="invalid or expired"):
        vscode_terminal._consume_ticket(token)


def test_vscode_terminal_router_exposes_repository_scoped_operations():
    paths = {getattr(route, "path", "") for route in vscode_terminal.router.routes}

    assert "/vscode-terminal/repositories" in paths
    assert "/vscode-terminal/repositories/{repository_id}/start" in paths
    assert "/vscode-terminal/repositories/{repository_id}/ticket" in paths
    assert (
        "/vscode-terminal/repositories/{repository_id}/terminal/{terminal_id}"
        in paths
    )
