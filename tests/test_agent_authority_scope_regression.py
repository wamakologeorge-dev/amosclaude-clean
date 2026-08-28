from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from amoscloud_ai.api.routes import agent


def _request(token: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode("utf-8")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "query_string": b"",
        }
    )


def test_agent_exports_authority_scope_helpers() -> None:
    assert callable(agent._authenticated_user)
    assert callable(agent._require_authority_scope)
    assert callable(agent._require_mode_scope)


def test_authority_credential_keeps_scope_boundary(monkeypatch) -> None:
    monkeypatch.setattr(agent, "get_user_from_session", lambda _token: None)
    monkeypatch.setattr(agent, "authenticate_autonomous_key", lambda _token: None)

    principal = {
        "authenticated": True,
        "principal_type": "amosclaud",
        "credential_type": "action",
        "credential_id": 7,
        "user_id": 11,
        "name": "Action Owner",
        "email": "owner@example.com",
        "is_admin": False,
        "provider": "password",
        "scopes": ["github:read", "fix"],
        "workspace_id": None,
        "expires_at": None,
        "required_scope": None,
        "scope_granted": True,
    }
    monkeypatch.setattr(
        agent.authority,
        "verify_credential",
        lambda _raw, required_scope=None: {
            **principal,
            "required_scope": required_scope,
            "scope_granted": agent.authority.scope_allowed(principal, required_scope),
        },
    )

    user = agent._authenticated_user(_request("amos_action_test"))
    assert user["id"] == 11
    assert user["_amosclaud_principal"]["credential_id"] == 7

    agent._require_authority_scope(user, "github:read")
    agent._require_mode_scope(user, "fix")

    with pytest.raises(HTTPException) as denied:
        agent._require_authority_scope(user, "github:write")
    assert denied.value.status_code == 403

    with pytest.raises(HTTPException) as denied_mode:
        agent._require_mode_scope(user, "deploy")
    assert denied_mode.value.status_code == 403


def test_legacy_autonomous_key_keeps_existing_mode_skills() -> None:
    legacy_user = {
        "id": 3,
        "name": "Legacy Agent",
        "email": "legacy@example.com",
        "is_admin": 0,
        "provider": "password",
        "key_id": 4,
        "autonomous_skills": '["fix","inspect"]',
    }

    agent._require_mode_scope(legacy_user, "fix")

    with pytest.raises(HTTPException) as denied:
        agent._require_mode_scope(legacy_user, "deploy")
    assert denied.value.status_code == 403

    with pytest.raises(HTTPException) as authority_only:
        agent._require_authority_scope(legacy_user, "github:read")
    assert authority_only.value.status_code == 403


def test_signed_in_user_stays_under_normal_platform_governance() -> None:
    session_user = {
        "id": 1,
        "name": "Signed In User",
        "email": "user@example.com",
        "is_admin": 0,
        "provider": "password",
    }

    agent._require_authority_scope(session_user, "github:read")
    agent._require_mode_scope(session_user, "deploy")
