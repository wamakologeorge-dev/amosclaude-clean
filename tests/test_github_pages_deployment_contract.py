from pathlib import Path

from amoscloud_ai.main import create_app


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pages.yml"
INDEX = ROOT / "pages-site" / "index.html"
APP = ROOT / "pages-site" / "app.js"
DEPLOYMENTS = ROOT / "amoscloud_ai" / "api" / "routes" / "deployments.py"


def test_legacy_pages_report_route_remains_registered_for_compatibility() -> None:
    paths = {getattr(route, "path", "") for route in create_app().routes}
    assert "/api/v1/deployments/github-pages/report" in paths


def test_pages_workflow_verifies_and_reports_deployment() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "Deploy Amosclaud Agent Issue Hub" in workflow
    assert "Verify Pages hub is static and token-free" in workflow
    assert "Verify deployed GitHub Page" in workflow
    assert "curl --location" in workflow
    assert "deployment-evidence.html" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "github_pat_" in workflow
    assert "localStorage.*token" in workflow
    assert "/api/v1/deployments/github-pages/report" not in workflow
    assert "AMOSCLAUD_DEPLOYMENT_WORKER_KEY" not in workflow


def test_agent_issue_hub_is_token_free_and_connects_both_repositories() -> None:
    index = INDEX.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")
    assert "No GitHub token is collected or stored" in index
    assert "wamakologeorge-dev/Amosclaud1" in app
    assert "wamakologeorge-dev/amosclaude-clean" in app
    assert "issues/new" in app
    assert "command-timeline" in index
    assert "localStorage" not in app
    assert "sessionStorage" not in app


def test_legacy_pages_report_still_requires_worker_authentication() -> None:
    source = DEPLOYMENTS.read_text(encoding="utf-8")
    assert "class GitHubPagesDeploymentReport" in source
    assert "_require_worker_key(x_api_key)" in source
    assert '"/github-pages/report"' in source
    assert 'environment="github-pages"' in source
    assert "body.verified" in source
    assert "body.health_status == \"healthy\"" in source
