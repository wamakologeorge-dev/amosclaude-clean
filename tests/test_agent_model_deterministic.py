from __future__ import annotations

import json

from src.agent import model as model_module
from src.agent.model import AutonomousModelGateway, ModelConfig


def test_explicit_action_test_document_does_not_require_remote_model(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/example")
    gateway = AutonomousModelGateway(ModelConfig(endpoint="", model="test", api_key=None))
    objective = """Create a new file named docs/AMOSCLAUD_ACTION_TEST.md.

The file must contain:
- the current repository name;
- the purpose of this test;
- the date the task was executed;
- a statement that Amosclaud created a real repository change.

Create a dedicated branch, commit the file, open a draft pull request, and do not merge it.
"""

    proposal = json.loads(gateway.complete(objective, []))

    assert proposal["changes"][0]["path"] == "docs/AMOSCLAUD_ACTION_TEST.md"
    content = proposal["changes"][0]["content"]
    assert "owner/example" in content
    assert "Purpose" in content
    assert "Executed" in content
    assert "Amosclaud created a real repository change" in content


def test_deterministic_fallback_rejects_source_and_protected_paths() -> None:
    gateway = AutonomousModelGateway(ModelConfig(endpoint="", model="test", api_key=None))

    assert (
        gateway._deterministic_file_creation(
            "Create a new file named src/unsafe.py containing the current repository name"
        )
        is None
    )
    assert (
        gateway._deterministic_file_creation(
            "Create a new file named .github/workflows/unsafe.md containing the current repository name"
        )
        is None
    )


def test_remote_completion_uses_configured_timeout(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Result:
        ok = True
        error = None
        reply = (
            '{"diagnosis":"test","changes":[{"path":"result.txt",'
            '"content":"verified","reason":"test"}],"verification":[]}'
        )

    def fake_reply(history, system_prompt, *, timeout=None):
        captured["history"] = history
        captured["system_prompt"] = system_prompt
        captured["timeout"] = timeout
        return Result()

    monkeypatch.setattr(model_module.native_provider, "reply", fake_reply)
    gateway = AutonomousModelGateway(
        ModelConfig(endpoint="https://example.invalid", model="test", api_key="token", timeout_seconds=17)
    )

    response = gateway.complete("repair result.txt", ["verified failure evidence"])

    assert json.loads(response)["changes"][0]["path"] == "result.txt"
    assert captured["timeout"] == 17
