from __future__ import annotations

import json

import pytest

from amoscloud_ai import engineering_agent


def test_workspace_cannot_escape_root(tmp_path):
    with pytest.raises(engineering_agent.EngineeringAgentError):
        engineering_agent._workspace(tmp_path, "../outside")


def test_protected_paths_are_rejected(tmp_path):
    with pytest.raises(engineering_agent.EngineeringAgentError):
        engineering_agent._validate_change(tmp_path, {"path": ".env", "content": "SECRET=value"})


def test_plan_only_does_not_write(monkeypatch, tmp_path):
    source = tmp_path / "app.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")

    class Result:
        status = "ready"
        runtime = "test"
        reply = json.dumps({
            "summary": "Update value",
            "changes": [{"path": "app.py", "content": "VALUE = 2\n", "reason": "requested"}],
        })

    monkeypatch.setattr(engineering_agent.provider, "reply", lambda *_args, **_kwargs: Result())
    result = engineering_agent.run_engineering_agent(tmp_path, "update value", apply_changes=False)

    assert result.applied is False
    assert source.read_text(encoding="utf-8") == "VALUE = 1\n"
    assert result.changes[0].status == "planned"


def test_apply_creates_backup(monkeypatch, tmp_path):
    source = tmp_path / "app.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")

    class Result:
        status = "ready"
        runtime = "test"
        reply = json.dumps({
            "summary": "Update value",
            "changes": [{"path": "app.py", "content": "VALUE = 2\n", "reason": "requested"}],
        })

    monkeypatch.setattr(engineering_agent.provider, "reply", lambda *_args, **_kwargs: Result())
    monkeypatch.setattr(engineering_agent, "_checks", lambda *_args: [])
    result = engineering_agent.run_engineering_agent(tmp_path, "update value", apply_changes=True)

    assert source.read_text(encoding="utf-8") == "VALUE = 2\n"
    assert (tmp_path / ".amosclaud" / "backups" / result.run_id / "app.py").read_text() == "VALUE = 1\n"
