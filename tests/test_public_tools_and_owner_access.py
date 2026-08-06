from pathlib import Path

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from amoscloud_ai.api.routes import auth, owner_access_gateway, public_developer_tools

ROOT = Path(__file__).resolve().parents[1]


def _request(path: str = "/api/v1/open-source/tools") -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("www.amosclaud.com", 443),
            "root_path": "",
        }
    )


def test_open_source_tool_catalog_requires_no_account() -> None:
    payload = public_developer_tools.open_source_tools(_request())

    assert payload["access"] == "public"
    assert payload["account_required"] is False
    assert payload["source_repository"].endswith("/amosclaude-clean")
    assert all(tool["account_required"] is False for tool in payload["tools"])
    assert {tool["id"] for tool in payload["tools"]} >= {
        "source",
        "linux-server",
        "vscode",
        "ide-cli",
        "mcp",
    }
    assert payload["paid_amosclaud_features"]["account_required"] is True


def test_public_developer_routes_are_mounted_before_the_platform() -> None:
    combined = (ROOT / "amoscloud_ai/combined_app.py").read_text(encoding="utf-8")
    login = (ROOT / "web/login.html").read_text(encoding="utf-8")

    public_index = combined.index("app.include_router(public_developer_tools.router)")
    platform_index = combined.index('app.mount("/", platform_app')
    assert public_index < platform_index
    assert 'href="/developer-tools"' in login
    assert "Continue without an account" in login


def test_configured_owner_can_bootstrap_only_the_first_account_when_mail_is_down(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "owner-bootstrap.db")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")

    def unavailable(_body):
        raise HTTPException(status_code=503, detail="mail unavailable")

    monkeypatch.setattr(auth, "request_registration_code", unavailable)
    response = Response()
    result = owner_access_gateway.request_registration_or_owner_bootstrap(
        auth.RegisterCodeRequest(
            name="George Mmakulu",
            email="gmmakulu@gmail.com",
            password="owner-password-123",
        ),
        response,
    )

    assert result["account_created"] is True
    assert "amos_session=" in response.headers["set-cookie"]
    with auth._connect() as db:
        owner = db.execute(
            "SELECT email,is_admin FROM users WHERE email=?",
            ("gmmakulu@gmail.com",),
        ).fetchone()
    assert owner["is_admin"] == 1

    with pytest.raises(HTTPException) as error:
        owner_access_gateway.request_registration_or_owner_bootstrap(
            auth.RegisterCodeRequest(
                name="Another Owner",
                email="gmmakulu@gmail.com",
                password="another-password-123",
            ),
            Response(),
        )
    assert error.value.status_code == 503


def test_unconfigured_email_never_receives_owner_fallback(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "non-owner-bootstrap.db")

    def unavailable(_body):
        raise HTTPException(status_code=503, detail="mail unavailable")

    monkeypatch.setattr(auth, "request_registration_code", unavailable)
    with pytest.raises(HTTPException) as error:
        owner_access_gateway.request_registration_or_owner_bootstrap(
            auth.RegisterCodeRequest(
                name="Unknown Person",
                email="unknown@example.com",
                password="unknown-password-123",
            ),
            Response(),
        )
    assert error.value.status_code == 503
    with auth._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
