"""Regression: the owner-bootstrap signup proxy must match auth's signature.

2026-08-24 production incident: ``POST /api/v1/auth/register/request-code``
returned HTTP 500 because ``owner_bootstrap`` proxied
``auth.request_registration_code(body)`` after that function grew a required
``response`` parameter. No test covered the proxy route, so the whole suite
stayed green while live signup crashed.
"""

from __future__ import annotations

from fastapi import HTTPException
from fastapi.testclient import TestClient

from amoscloud_ai.api.routes import auth
from amoscloud_ai.main import create_app


def _client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "auth.db")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.invalid")
    return TestClient(create_app(), raise_server_exceptions=False)


def test_register_request_code_survives_the_proxy_when_mail_is_down(monkeypatch, tmp_path) -> None:
    def mail_down(*_args, **_kwargs):
        raise HTTPException(status_code=503, detail="mail lane down")

    monkeypatch.setattr(auth, "_send_code", mail_down)
    client = _client(monkeypatch, tmp_path)

    response = client.post(
        "/api/v1/auth/register/request-code",
        json={
            "email": "new-user@example.com",
            "name": "New User",
            "password": "Sturdy-Passw0rd-2026!",
        },
    )

    assert response.status_code != 500, response.text
    assert response.status_code in (200, 202)


def test_register_request_code_proxy_forwards_when_mail_sends(monkeypatch, tmp_path) -> None:
    sent: list[tuple[str, str]] = []

    def record_send(email: str, code: str, purpose: str) -> None:
        sent.append((email, purpose))

    monkeypatch.setattr(auth, "_send_code", record_send)
    client = _client(monkeypatch, tmp_path)

    response = client.post(
        "/api/v1/auth/register/request-code",
        json={
            "email": "happy-user@example.com",
            "name": "Happy User",
            "password": "Sturdy-Passw0rd-2026!",
        },
    )

    assert response.status_code in (200, 202), response.text
    assert sent == [("happy-user@example.com", "register")]
