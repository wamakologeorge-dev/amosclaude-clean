from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from amoscloud_ai.api.routes import auth, public_developer_tools

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


def test_public_catalog_exposes_source_but_not_free_official_execution() -> None:
    payload = public_developer_tools.open_source_tools(_request())

    assert payload["access"] == "public_source_only"
    assert payload["account_required"] is False
    assert payload["source_repository"].endswith("/amosclaude-clean")
    assert all(resource["account_required"] is False for resource in payload["public_resources"])
    assert {resource["id"] for resource in payload["public_resources"]} == {
        "source",
        "documentation",
        "license",
    }
    assert payload["official_tools"]["account_required"] is True
    assert payload["official_tools"]["verified_support_time_required"] is True
    assert payload["official_tools"]["support_url"].endswith("/organization-support")


def test_public_account_and_github_routes_precede_paid_platform() -> None:
    combined = (ROOT / "amoscloud_ai/combined_app.py").read_text(encoding="utf-8")
    login = (ROOT / "web/login.html").read_text(encoding="utf-8")

    public_index = combined.index("app.include_router(public_developer_tools.router)")
    github_index = combined.index("app.include_router(github_access_gateway.router)")
    platform_index = combined.index('app.mount("/", HostedToolSupportASGI(platform_app)')
    assert public_index < platform_index
    assert github_index < platform_index
    assert "location.replace('/auth/github')" not in login
    assert "<form" in login
    assert 'type="password"' in login
    assert "/static/login.js" in login
    assert "Username" in login
    assert "Scan secure QR code" in login
    assert 'href="/auth/github/admin-login"' not in login
    assert "Sign in directly as platform owner" not in login


def test_mail_failure_never_creates_an_unverified_account(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "mail-failure.db")

    def unavailable(_email: str, _code: str, _purpose: str) -> None:
        raise HTTPException(status_code=503, detail="mail unavailable")

    monkeypatch.setattr(auth, "_send_code", unavailable)
    with pytest.raises(HTTPException) as error:
        auth.request_registration_code(
            auth.RegisterCodeRequest(
                name="Developer",
                email="developer@example.com",
                password="developer-password-123",
            )
        )

    assert error.value.status_code == 503
    with auth._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM auth_codes").fetchone()[0] == 0


def test_owner_recovery_is_separate_from_public_registration() -> None:
    owner_gateway = (ROOT / "amoscloud_ai/api/routes/owner_access_gateway.py").read_text(
        encoding="utf-8"
    )
    owner_bootstrap = (ROOT / "amoscloud_ai/api/routes/owner_bootstrap.py").read_text(
        encoding="utf-8"
    )

    assert '@router.get("/github/admin-login"' in owner_gateway
    assert '@router.get("/github/admin-callback"' in owner_gateway
    assert "request_registration_or_owner_bootstrap" not in owner_gateway
    assert "RegisterCodeRequest" not in owner_gateway
    assert 'RedirectResponse("/admin?github=owner"' in owner_bootstrap
