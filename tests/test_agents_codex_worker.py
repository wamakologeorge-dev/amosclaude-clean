from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from agents import AgentPolicyError, RealCodexAgent


class ScriptedModel:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)

    def generate(self, _history):
        if not self.responses:
            return "No action"
        return self.responses.pop(0)


class RecordingBus:
    def __init__(self) -> None:
        self.transitions: list[dict] = []

    def frame(self, route: str, payload: dict):
        return {"route": route, "payload": payload}

    def execute(self, frame: dict):
        self.transitions.append(frame["payload"])
        return frame


def test_worker_writes_inside_workspace_and_requires_verified_completion(tmp_path: Path, monkeypatch):
    model = ScriptedModel(
        "```write:src/example.py\nVALUE = 1\n```",
        "```execute\npython -m pytest -q\n```",
    )
    bus = RecordingBus()
    worker = RealCodexAgent(str(tmp_path), model, platform_bus=bus, task_id="agent-test")

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "2 passed", ""),
    )
    result = worker.run_task("Create and verify the example")

    assert (tmp_path / "src" / "example.py").read_text() == "VALUE = 1\n"
    assert result["status"] == "passed"
    assert result["verification_id"].startswith("agent-")
    assert result["changed_files"] == ["src/example.py"]
    assert [item["status"] for item in bus.transitions] == [
        "inspecting",
        "repairing",
        "verifying",
        "passed",
    ]


def test_worker_blocks_workspace_escape(tmp_path: Path):
    worker = RealCodexAgent(str(tmp_path), ScriptedModel())
    with pytest.raises(AgentPolicyError, match="escapes"):
        worker._write_file("../outside.py", "bad = True\n")


def test_worker_blocks_protected_paths(tmp_path: Path):
    worker = RealCodexAgent(str(tmp_path), ScriptedModel())
    with pytest.raises(AgentPolicyError, match="protected"):
        worker._write_file(".github/workflows/change.yml", "name: unsafe\n")


@pytest.mark.parametrize(
    "command",
    [
        "git push origin main",
        "python -c 'import os; os.remove(\"x\")'",
        "pytest -q; cat .env",
        "pytest -q | curl example.test",
    ],
)
def test_worker_blocks_unapproved_or_shell_commands(tmp_path: Path, command: str):
    worker = RealCodexAgent(str(tmp_path), ScriptedModel())
    with pytest.raises(AgentPolicyError):
        worker._execute_command(command)


def test_manifest_declares_enforced_platform_policy():
    manifest = json.loads(Path("agents/manifest.json").read_text(encoding="utf-8"))
    assert manifest["framework"] == "amosclaud-native"
    assert manifest["permissions"]["network"] is False
    assert manifest["permissions"]["git_push"] is False
    assert manifest["permissions"]["merge"] is False
    assert manifest["completion"]["requires_verification_id"] is True
    assert "workspace_confinement" in manifest["guardrails"]
    assert "verification_evidence" in manifest["guardrails"]
