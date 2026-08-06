from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_organization_identity_routes_are_mounted() -> None:
    organizations = _read("amoscloud_ai/api/routes/organizations.py")
    identity = _read("amoscloud_ai/api/routes/organization_identity.py")

    assert "router.routes.extend(organization_identity.router.routes)" in organizations
    assert 'router = APIRouter(prefix="/organization-access"' in identity
    assert '@router.post("/register", status_code=201)' in identity
    assert '@router.post("/login")' in identity
    assert '@router.post("/join", status_code=201)' in identity
    assert '@router.post("/recover")' in identity


def test_identifiers_match_the_approved_structure() -> None:
    identity = _read("amoscloud_ai/api/routes/organization_identity.py")
    login = _read("web/login.html")

    assert '_ORG_ID_RE = re.compile(r"^[0-9]{5}$")' in identity
    assert '_MEMBER_RE = re.compile(r"^[0-9]{4}$")' in identity
    assert 'return f"{public_id}-{member_number}"' in identity
    assert "11111-2131" in login
    assert "Exactly five numbers" in login


def test_secrets_and_recovery_codes_are_hashed() -> None:
    identity = _read("amoscloud_ai/api/routes/organization_identity.py")
    docs = _read("docs/organization-identity.md")

    assert "organization_join_secrets" in identity
    assert "organization_recovery_codes" in identity
    assert "_token_hash(_canonical_secret(access_code))" in identity
    assert "_token_hash(_canonical_secret(code))" in identity
    assert "secrets.token_hex(8).upper()" in identity
    assert "shown once and stored only as hashes" in docs


def test_organization_admin_can_revoke_membership_but_not_final_owner() -> None:
    identity = _read("amoscloud_ai/api/routes/organization_identity.py")

    assert '@router.delete("/{public_id}/members/{member_number}"' in identity
    assert "SET status='revoked',removed_at=?,updated_at=?" in identity
    assert 'db.execute("DELETE FROM sessions WHERE user_id=?"' in identity
    assert "Transfer ownership before removing the final owner" in identity
    assert "Only an owner can remove an owner" in identity
    assert 'if target["provider"] == "organization"' in identity
    assert "UPDATE users SET password_hash=NULL" in identity


def test_revoked_members_are_excluded_from_workspace_authorization() -> None:
    workspaces = _read("amoscloud_ai/api/routes/workspaces.py")

    assert "om.status='active'" in workspaces
    assert "COALESCE(c.role,om.role)" in workspaces


def test_owner_controls_identifier_and_ownership_transfer() -> None:
    identity = _read("amoscloud_ai/api/routes/organization_identity.py")
    page = _read("web/organization-access.html")
    script = _read("web/organization-access.js")

    assert '@router.patch("/{public_id}/identifier")' in identity
    assert '@router.post("/{public_id}/transfer-ownership")' in identity
    assert 'if actor["role"] != "owner"' in identity
    assert "Owner access required" in identity
    assert "organization.ownership_transferred" in identity
    assert 'value="transfer-ownership"' in page
    assert "/transfer-ownership" in script


def test_login_page_is_the_primary_organization_access_portal() -> None:
    health = _read("amoscloud_ai/api/routes/health.py")
    login = _read("web/login.html")
    script = _read("web/unified-login.js")

    assert '@router.get("/organization-access", include_in_schema=False)' in health
    assert 'id="organization-access-panel"' in login
    assert 'id="email-access-panel"' in login
    assert 'src="/static/unified-login.js"' in login
    assert "/api/v1/organization-access/login" in script
    assert "/api/v1/organization-access/register" in script
    assert "/api/v1/organization-access/join" in script
    assert "/api/v1/organization-access/recover" in script


def test_organization_signup_shows_only_the_fields_needed_for_each_mode() -> None:
    login = _read("web/login.html")
    script = _read("web/unified-login.js")
    login_css = _read("web/login.css")
    legacy_css = _read("web/organization-access.css")

    assert 'id="organization-name-field" hidden' in login
    assert 'id="organization-access-code-field" hidden' in login
    assert 'id="organization-recovery-code-field" hidden' in login
    assert "Only four fields. No email code is required." in script
    assert "Use a short username, not an email" in script
    assert "[hidden], .hidden { display: none !important; }" in login_css
    assert "[hidden] { display: none !important; }" in legacy_css


def test_organization_credential_routes_are_rate_limited() -> None:
    security = _read("amoscloud_ai/security.py")

    for path in (
        "/api/v1/organization-access/register",
        "/api/v1/organization-access/login",
        "/api/v1/organization-access/join",
        "/api/v1/organization-access/recover",
    ):
        assert path in security
