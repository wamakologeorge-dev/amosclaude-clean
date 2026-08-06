from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from amoscloud_ai.api.routes import auth, google_auth
from amoscloud_ai.main import create_app


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _FakeGoogleClient:
    profile = {
        "sub": "google-subject-123",
        "email": "person@example.com",
        "email_verified": True,
        "name": "Google Person",
    }

    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, **kwargs):
        assert url == google_auth.GOOGLE_TOKEN_URL
        assert kwargs["data"]["grant_type"] == "authorization_code"
        return _FakeResponse({"access_token": "google-access-token"})

    async def get(self, url, **kwargs):
        assert url == google_auth.GOOGLE_USERINFO_URL
        assert kwargs["headers"]["Authorization"] == "Bearer google-access-token"
        return _FakeResponse(dict(self.profile))


def _configure(monkeypatch, tmp_path):
    auth.DB_PATH = tmp_path / "google-auth.db"
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv(
        "GOOGLE_CALLBACK_URL",
        "https://www.amosclaud.com/api/v1/auth/google/callback",
    )
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setattr(google_auth.httpx, "AsyncClient", _FakeGoogleClient)


def _complete_google_login(client):
    start = client.get("/api/v1/auth/google", follow_redirects=False)
    assert start.status_code == 302
    query = parse_qs(urlparse(start.headers["location"]).query)
    assert query["client_id"] == ["client.apps.googleusercontent.com"]
    assert query["scope"] == ["openid email profile"]
    assert query["redirect_uri"] == ["https://www.amosclaud.com/api/v1/auth/google/callback"]
    state = client.cookies.get(google_auth.GOOGLE_STATE_COOKIE)
    assert state
    return client.get(
        f"/api/v1/auth/google/callback?code=code-123&state={state}",
        follow_redirects=False,
    )


def test_google_status_is_disabled_without_credentials(monkeypatch, tmp_path):
    auth.DB_PATH = tmp_path / "google-disabled.db"
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)

    with TestClient(create_app()) as client:
        response = client.get("/api/v1/auth/google/status")

    assert response.status_code == 200
    assert response.json() == {"enabled": False, "callback_url": None}


def test_legacy_google_module_can_read_existing_identity_data(monkeypatch, tmp_path):
    """The inner module remains migration-compatible but is not publicly routed."""

    _configure(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        first = _complete_google_login(client)
        assert first.status_code == 302
        assert first.headers["location"] == "/cloud/agent?auth=google"

        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["email"] == "person@example.com"
        assert me.json()["provider"] == "google"

        second = _complete_google_login(client)
        assert second.status_code == 302

    with auth._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM oauth_identities").fetchone()[0] == 1


def test_legacy_google_module_links_existing_account(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    with auth._connect() as db:
        db.execute(
            """
            INSERT INTO users(name,email,password_hash,provider,is_admin,created_at)
            VALUES (?,?,?,?,0,?)
            """,
            (
                "Existing Person",
                "person@example.com",
                auth._hash_password("safe-password-123"),
                "password",
                "2026-07-29T00:00:00+00:00",
            ),
        )
        db.commit()

    with TestClient(create_app()) as client:
        response = _complete_google_login(client)
        assert response.status_code == 302

    with auth._connect() as db:
        user = db.execute("SELECT provider FROM users WHERE email='person@example.com'").fetchone()
        assert user["provider"] == "password+google"
        assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def test_legacy_google_module_rejects_state_mismatch(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        start = client.get("/api/v1/auth/google", follow_redirects=False)
        assert start.status_code == 302
        response = client.get(
            "/api/v1/auth/google/callback?code=code-123&state=wrong-state",
            follow_redirects=False,
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid Google OAuth state"


def test_legacy_google_module_requires_verified_email(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    monkeypatch.setattr(
        _FakeGoogleClient,
        "profile",
        {
            "sub": "google-subject-123",
            "email": "person@example.com",
            "email_verified": False,
            "name": "Google Person",
        },
    )

    with TestClient(create_app()) as client:
        response = _complete_google_login(client)

    assert response.status_code == 302
    assert response.headers["location"] == "/login?google_error=unverified_email"
    with auth._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_production_gateway_disables_google_as_public_account_provider():
    login = open("web/login.html", encoding="utf-8").read()
    gateway = open("amoscloud_ai/api/routes/github_access_gateway.py", encoding="utf-8").read()
    environment = open(".env.production.example", encoding="utf-8").read()

    assert "google-login-button" not in login
    assert '@router.get("/auth/google"' in gateway
    assert '@router.get("/auth/google/callback"' in gateway
    assert 'RedirectResponse("/auth/github"' in gateway
    assert '"provider": "github"' in gateway
    assert "GOOGLE_CLIENT_ID=\n" in environment
    assert "GOOGLE_CALLBACK_URL=\n" in environment
