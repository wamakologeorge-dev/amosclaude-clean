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
    page = _read("web/organization-access.html")

    assert '_ORG_ID_RE = re.compile(r"^[0-9]{5}$")' in identity
    assert '_MEMBER_RE = re.compile(r"^[0-9]{4}$")' in identity
    assert 'return f"{public_id}-{member_number}"' in identity
    assert "11111-2131" in page
    assert "Organization IDs contain exactly five numbers" in page


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


def test_owner_controls_identifier_and_ownership_transfer() -> None:
    identity = _read("amoscloud_ai/api/routes/organization_identity.py")

    assert '@router.patch("/{public_id}/identifier")' in identity
    assert '@router.post("/{public_id}/transfer-ownership")' in identity
    assert 'if actor["role"] != "owner"' in identity
    assert "Owner access required" in identity
    assert "organization.ownership_transferred" in identity


def test_login_page_exposes_public_organization_access() -> None:
    health = _read("amoscloud_ai/api/routes/health.py")
    login = _read("web/login.html")
    page = _read("web/organization-access.html")
    script = _read("web/organization-access.js")

    assert '@router.get("/organization-access", include_in_schema=False)' in health
    assert 'FileResponse(WEB_DIR / "organization-access.html")' in health
    assert 'href="/organization-access"' in login
    assert "No email code required" in page
    assert "/api/v1/organization-access/login" in script
    assert "/api/v1/organization-access/register" in script
    assert "/api/v1/organization-access/join" in script
    assert "/api/v1/organization-access/recover" in script


def test_organization_credential_routes_are_rate_limited() -> None:
    security = _read("amoscloud_ai/security.py")

    for path in (
        "/api/v1/organization-access/register",
        "/api/v1/organization-access/login",
        "/api/v1/organization-access/join",
        "/api/v1/organization-access/recover",
    ):
        assert path in security
