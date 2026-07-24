from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "web" / "index.html"
RUNTIME = ROOT / "web" / "unified-agent-runtime.js"


def test_agent_surface_shows_native_project_context() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert "Active project" in html
    assert 'id="active-workspace-name"' in html
    assert 'id="active-repository-name"' in html
    assert 'id="active-branch-name"' in html
    assert 'id="active-owner-authorization"' in html
    assert "repository_id" in html
    assert "selected workspace/repository" in html
    assert "server" in html.lower()


def test_agent_commands_receive_authenticated_repository_context() -> None:
    source = RUNTIME.read_text(encoding="utf-8")
    assert "amosclaud.activeProjectContext" in source
    assert "repository_id:" in source
    assert "workspace_id:" in source
    assert "selected_repository:" in source
    assert "selected_workspace:" in source
    assert "owner_authorization:" in source
    assert "issue_title:" in source
    assert "issue_description:" in source
    assert "operation: 'create_issue'" in source
    assert "operation: 'create_repository'" in source
    assert "Execute this action now" in source
    assert "/api/v1/core/os/execute" in source
    assert "execution_contract: 'native-or-truthful-blocker'" in source
    assert "use_agent: true" in source
    assert "apply_changes: true" in source
    assert "require_verification: true" in source
    assert "return_evidence: true" in source
