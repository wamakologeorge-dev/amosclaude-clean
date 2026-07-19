from pathlib import Path

from amoscloud_ai.autonomous_server import _execution_root


def test_trusted_repository_workspace_becomes_execution_root(tmp_path):
    storage_root = tmp_path / "repositories"
    workspace = storage_root / "42"
    (workspace / ".git").mkdir(parents=True)

    root = _execution_root(
        {
            "trusted_repository_workspace": str(workspace),
            "trusted_repository_storage_root": str(storage_root),
        }
    )

    assert root == workspace.resolve()


def test_autonomous_browser_sends_selected_repository():
    script = Path("web/conversational-agent.js").read_text(encoding="utf-8")
    page = Path("web/index.html").read_text(encoding="utf-8")

    assert 'id="agent-repository-input"' in page
    assert "fetch('/api/v1/repositories'" in script
    assert "repository_id: repositoryInput?.value ? Number(repositoryInput.value) : null" in script
