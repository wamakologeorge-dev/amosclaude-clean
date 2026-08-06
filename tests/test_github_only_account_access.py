from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

from starlette.requests import Request

from amoscloud_ai.api.routes import auth, github_access_gateway
from amoscloud_ai.main import create_app

ROOT = Path(__file__).resolve().parents[1]


def _request(path: str = "/auth/github") -> Request:
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


def test_email_account_portal_remains_the_primary_entry() -> None:
    page = (ROOT / "web/login.html").read_text(encoding="utf-8")

    assert "Create account" in page
    assert "Email me a sign-in code" in page
    assert "Forgot password?" in page
    assert '<form id="auth-form"' in page
    assert "location.replace('/auth/github')" not in page

    paths = {getattr(route, "path", "") for route in create_app().routes}
    assert "/auth/register/request-code" in paths
    assert "/auth/register/verify" in paths
    assert "/auth/login" in paths
    assert "/auth/password/forgot" in paths
    assert "/auth/password/reset" in paths


def test_github_is_optional_and_requests_identity_only(monkeypatch) -> None:
    monkeypatch.setattr(auth, "get_user_from_session", lambda _token: None)
    monkeypatch.setenv("GITHUB_CLIENT_ID", "github-client-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "github-client-secret")
    monkeypatch.setenv("GITHUB_CALLBACK_URL", "https://www.amosclaud.com/auth/github/callback")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")

    response = github_access_gateway.github_account_access(_request())
    parsed = urlparse(response.headers["location"])
    query = parse_qs(parsed.query)

    assert response.status_code == 302
    assert parsed.netloc == "github.com"
    assert parsed.path == "/login/oauth/authorize"
    assert query["client_id"] == ["github-client-id"]
    assert query["allow_signup"] == ["true"]
    assert query["redirect_uri"] == ["https://www.amosclaud.com/auth/github/callback"]
    assert query["scope"] == ["read:user user:email"]
    assert "repo" not in query["scope"][0]
    assert github_access_gateway.GITHUB_STATE_COOKIE in response.headers.getlist("set-cookie")[0]


def test_first_github_authorization_creates_non_admin_account_and_returning_user_signs_in(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "optional-github.db")
    profile = {"id": 12345, "login": "new-developer", "name": "New Developer"}
    emails = [
        {
            "email": "developer@example.com",
            "verified": True,
            "primary": True,
        }
    ]

    first_user_id, created, first_token = github_access_gateway._find_or_create_github_user(
        profile,
        emails,
    )
    second_user_id, created_again, second_token = github_access_gateway._find_or_create_github_user(
        profile, emails
    )

    assert created is True
    assert created_again is False
    assert first_user_id == second_user_id
    assert first_token != second_token

    with auth._connect() as db:
        users = db.execute(
            "SELECT id,name,email,password_hash,github_id,provider,is_admin FROM users"
        ).fetchall()
    assert len(users) == 1
    assert users[0]["name"] == "New Developer"
    assert users[0]["email"] == "developer@example.com"
    assert users[0]["password_hash"] is None
    assert users[0]["github_id"] == "12345"
    assert users[0]["provider"] == "github"
    assert users[0]["is_admin"] == 0


def test_private_email_github_account_can_still_sign_in(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "private-github-email.db")
    profile = {"id": 777, "login": "private-developer", "name": None, "email": None}

    user_id, created, _ = github_access_gateway._find_or_create_github_user(profile, [])

    assert created is True
    with auth._connect() as db:
        user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    assert user["name"] == "private-developer"
    assert user["email"] == "github-777@users.noreply.amosclaud.local"
    assert user["provider"] == "github"


def test_unverified_profile_email_cannot_take_over_existing_account(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "unverified-email.db")
    with auth._connect() as db:
        cursor = db.execute(
            """INSERT INTO users(
                   name,email,password_hash,provider,is_admin,created_at
               ) VALUES ('Existing','victim@example.com',NULL,'password',0,'now')"""
        )
        existing_id = int(cursor.lastrowid)
        db.commit()

    new_id, created, _ = github_access_gateway._find_or_create_github_user(
        {
            "id": 999,
            "login": "unverified-profile",
            "name": "Unverified",
            "email": "victim@example.com",
        },
        [],
    )

    assert created is True
    assert new_id != existing_id
    with auth._connect() as db:
        existing = db.execute("SELECT github_id FROM users WHERE id=?", (existing_id,)).fetchone()
        new_user = db.execute("SELECT email,github_id FROM users WHERE id=?", (new_id,)).fetchone()
    assert existing["github_id"] is None
    assert new_user["email"] != "victim@example.com"
    assert new_user["github_id"] == "999"


def test_verified_github_email_links_matching_email_account_without_removing_password(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "verified-link.db")
    password_hash = auth._hash_password("safe-password-123")
    with auth._connect() as db:
        cursor = db.execute(
            """INSERT INTO users(
                   name,email,password_hash,provider,is_admin,created_at
               ) VALUES (?,?,?,?,0,'now')""",
            ("Existing", "verified@example.com", password_hash, "password"),
        )
        existing_id = int(cursor.lastrowid)
        db.commit()

    user_id, created, _ = github_access_gateway._find_or_create_github_user(
        {"id": 555, "login": "verified-developer", "name": "Verified"},
        [{"email": "verified@example.com", "verified": True, "primary": True}],
    )

    assert created is False
    assert user_id == existing_id
    with auth._connect() as db:
        user = db.execute(
            "SELECT github_id,provider,password_hash FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
    assert user["github_id"] == "555"
    assert user["provider"] == "password"
    assert user["password_hash"] == password_hash


def test_github_gateway_does_not_shadow_email_account_routes() -> None:
    gateway_paths = {route.path for route in github_access_gateway.router.routes}

    assert "/login" not in gateway_paths
    assert "/signup" not in gateway_paths
    assert "/create-account" not in gateway_paths
    assert "/auth/login" not in gateway_paths
    assert "/auth/register/request-code" not in gateway_paths
    assert "/auth/password/reset" not in gateway_paths
