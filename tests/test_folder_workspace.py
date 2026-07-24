from pathlib import Path

import pytest

from amoscloud_ai.core.tokens import AmosclaudTokenService
from amoscloud_ai.core.workspace import WorkspaceEngine, WorkspaceError


def test_workspace_initializes_portable_folder_tree(tmp_path: Path):
    engine = WorkspaceEngine(tmp_path / "AmosclaudWorkspace")
    summary = engine.summary()

    assert summary["manifest"]["source_of_truth"] == "files"
    assert (engine.root / "projects").is_dir()
    assert (engine.root / "notes").is_dir()
    assert (engine.root / "tasks").is_dir()
    assert (engine.root / "agents").is_dir()
    assert (engine.root / "knowledge").is_dir()
    assert (engine.root / "automations").is_dir()
    assert (engine.root / "logs").is_dir()
    assert (engine.root / "backups").is_dir()


def test_workspace_creates_project_note_task_and_activity(tmp_path: Path):
    engine = WorkspaceEngine(tmp_path / "workspace")
    project = engine.create_project("Local Platform", "Folder-first project")
    note = engine.create_note("Architecture", "Files are the source of truth.", ["local-first"])
    task = engine.create_task("Build dashboard", "local-platform", "coding-agent")
    engine.append_activity({"action": "test.completed"})

    assert project["path"] == "projects/local-platform"
    assert note["path"] == "notes/architecture.md"
    assert task["parsed"]["status"] == "pending"
    assert "Files are the source of truth" in note["content"]
    assert (engine.root / "logs" / "activity.jsonl").exists()


def test_workspace_blocks_path_escape(tmp_path: Path):
    engine = WorkspaceEngine(tmp_path / "workspace")
    with pytest.raises(WorkspaceError, match="Invalid workspace path"):
        engine.read_item("../outside.txt")


def test_amo_token_is_shown_once_and_stored_as_hash(tmp_path: Path):
    db_path = tmp_path / "core.db"
    service = AmosclaudTokenService(db_path)
    issued = service.issue(
        name="Local agent",
        owner_id=1,
        scopes=["workspace:read", "workspace:write", "agent:run"],
        expires_in_days=30,
    )

    assert issued["token"].startswith("amo_token_")
    assert service.verify(issued["token"], "agent:run")["owner_id"] == 1
    assert service.verify(issued["token"], "router:write") is None
    assert issued["token"].encode() not in db_path.read_bytes()

    listed = service.list_for_owner(1)
    assert "token" not in listed[0]
    assert listed[0]["token_hint"].startswith("amo_token_")

    assert service.revoke(issued["id"], 1) is True
    assert service.verify(issued["token"], "agent:run") is None
