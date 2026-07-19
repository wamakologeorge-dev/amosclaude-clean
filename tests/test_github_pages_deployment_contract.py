from pathlib import Path

from amoscloud_ai.main import create_app


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pages.yml"
DEPLOYMENTS = ROOT / "amoscloud_ai" / "api" / "routes" / "deployments.py"


def test_pages_report_route_is_registered() -> None:
    paths = {getattr(route, "path", "") for route in create_app().routes}
    assert "/api/v1/deployments/github-pages/report" in paths


def test_pages_workflow_verifies_and_reports_deployment() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "Verify and report deployment to Amosclaud Autonomous" in workflow
    assert "curl --location" in workflow
    assert "deployment-evidence.json" in workflow
    assert "/api/v1/deployments/github-pages/report" in workflow
    assert "AMOSCLAUD_DEPLOYMENT_WORKER_KEY" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "rollback_ready" in workflow


def test_pages_report_requires_worker_authentication() -> None:
    source = DEPLOYMENTS.read_text(encoding="utf-8")
    assert "class GitHubPagesDeploymentReport" in source
    assert "_require_worker_key(x_api_key)" in source
    assert '"/github-pages/report"' in source
    assert 'environment="github-pages"' in source
    assert "body.verified" in source
    assert "body.health_status == \"healthy\"" in source
