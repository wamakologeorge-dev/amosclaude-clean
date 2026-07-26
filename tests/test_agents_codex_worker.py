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


def test_worker_aborts_after_repeated_no_action_responses(tmp_path: Path):
    model = ScriptedModel("thinking about it...", "still thinking")
    bus = RecordingBus()
    worker = RealCodexAgent(str(tmp_path), model, platform_bus=bus, task_id="agent-no-action")

    result = worker.run_task("Please do the thing")

    assert result["status"] == "failed"
    assert "repeated responses" in result["message"]
    assert result["changed_files"] == []
    assert [item["status"] for item in bus.transitions] == ["inspecting", "failed"]


def test_max_loops_failure_includes_last_verification_output(tmp_path: Path, monkeypatch):
    model = ScriptedModel(
        "```execute\npython -m pytest -q\n```",
        "```execute\npython -m pytest -q\n```",
    )
    worker = RealCodexAgent(str(tmp_path), model, max_loops=2)

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 1, "assert failed", "test_x: 1 failed"
        ),
    )
    result = worker.run_task("Verify the module")

    assert result["status"] == "failed"
    assert "Maximum self-correction loops" in result["message"]
    assert result["last_command"] == "python -m pytest -q"
    assert result["last_exit_code"] == 1
    assert "assert failed" in result["last_output"]
    assert "1 failed" in result["last_stderr"]


def test_failed_verification_feeds_actionable_prompt_to_model(tmp_path: Path, monkeypatch):
    prompts_received: list[str] = []

    class RecordingModel:
        def __init__(self) -> None:
            self.responses = [
                "```execute\npython -m pytest -q\n```",
                "```write:src/fix.py\nvalue = 2\n```",
                "```execute\npython -m pytest -q\n```",
            ]

        def generate(self, history):
            prompts_received.append(history[-1]["content"])
            return self.responses.pop(0)

    outcomes = iter(
        [
            subprocess.CompletedProcess(["pytest"], 1, "failing", "1 failed"),
            subprocess.CompletedProcess(["pytest"], 0, "1 passed", ""),
        ]
    )
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: next(outcomes))

    worker = RealCodexAgent(str(tmp_path), RecordingModel(), max_loops=5)
    result = worker.run_task("Verify the fix")

    assert result["status"] == "passed"
    assert (tmp_path / "src" / "fix.py").read_text() == "value = 2\n"
    review_prompts = [p for p in prompts_received if "Review this execution result" in p]
    assert review_prompts, "expected the failed verification to feed a review prompt back to the model"
    assert "verification failed (exit 1)" in review_prompts[0]


def test_manifest_declares_enforced_platform_policy():
    manifest = json.loads(Path("agents/manifest.json").read_text(encoding="utf-8"))
    assert manifest["framework"] == "amosclaud-native"
    assert manifest["permissions"]["network"] is False
    assert manifest["permissions"]["git_push"] is False
    assert manifest["permissions"]["merge"] is False
    assert manifest["completion"]["requires_verification_id"] is True
    assert "workspace_confinement" in manifest["guardrails"]
    assert "verification_evidence" in manifest["guardrails"]
