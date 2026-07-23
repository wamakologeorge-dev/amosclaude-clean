from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "amoscloud_ai" / "api" / "routes" / "approvals_api.py"
REVIEWS = ROOT / "amoscloud_ai" / "api" / "routes" / "reviews.py"
SECURITY = ROOT / "amoscloud_ai" / "security.py"
INDEX = ROOT / "pages-site" / "index.html"
CONFIG = ROOT / "pages-site" / "control-api-config.js"
QUEUE = ROOT / "pages-site" / "autonomous-approval-queue.js"


def test_approval_backend_is_mounted_under_api_v1() -> None:
    api = API.read_text(encoding="utf-8")
    reviews = REVIEWS.read_text(encoding="utf-8")
    assert 'APIRouter(prefix="/approvals"' in api
    assert '@router.post("/decision")' in api
    assert "router.include_router(approvals_api.router)" in reviews


def test_approval_decisions_require_identity_permission_and_single_use() -> None:
    api = API.read_text(encoding="utf-8")
    assert "get_user_from_session" in api
    assert "github_connections" in (ROOT / "amoscloud_ai" / "api" / "routes" / "github_repositories.py").read_text(encoding="utf-8")
    assert 'permissions.get(name)' in api
    assert 'admin", "maintain", "push' in api
    assert "website_approval_decisions" in api
    assert "approval_id TEXT NOT NULL UNIQUE" in api
    assert "Website approvals must be single-use" in api


def test_approval_backend_records_authoritative_github_evidence() -> None:
    api = API.read_text(encoding="utf-8")
    assert 'f"@amosclaud {body.decision}"' in api
    assert "AMOSCLAUD_COMMAND_REPOSITORY" in api
    assert "@amosclaud inspect the failed workflow evidence" in api
    assert '"recorded": True' in api
    assert '"github_record_url"' in api


def test_cross_site_approval_session_is_httponly_and_origin_restricted() -> None:
    api = API.read_text(encoding="utf-8")
    security = SECURITY.read_text(encoding="utf-8")
    assert '@router.get("/connect")' in api
    assert 'httponly=True' in api
    assert 'secure=True' in api
    assert 'samesite="none"' in api
    assert "AMOSCLAUD_WEBSITE_ORIGINS" in api
    assert "urlparse" in api
    assert 'host.endswith(".github.io")' in api or 'host == "github.io"' in api
    assert "Website origin is not authorized" in api
    assert "AMOSCLAUD_WEBSITE_ORIGINS" in security
    assert 'path.startswith("/api/v1/approvals/")' in security
    assert "self.trusted_origins | self.approval_origins" in security


def test_pages_loads_public_control_endpoint_without_browser_credentials() -> None:
    index = INDEX.read_text(encoding="utf-8")
    config = CONFIG.read_text(encoding="utf-8")
    queue = QUEUE.read_text(encoding="utf-8")
    assert "control-api-config.js" in index
    assert index.index("control-api-config.js") < index.index("autonomous-approval-queue.js")
    assert 'window.AMOSCLAUD_CONTROL_API = "https://www.amosclaud.com"' in config
    assert 'credentials: "include"' in queue
    combined = config + queue
    assert "github_pat_" not in combined
    assert "ghp_" not in combined
    assert "localStorage" not in combined
    assert "sessionStorage" not in combined
