from __future__ import annotations

import json

from src.agent.model import AutonomousModelGateway, ModelConfig


def test_explicit_action_test_document_does_not_require_remote_model(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/example")
    gateway = AutonomousModelGateway(
        ModelConfig(endpoint="", model="test", api_key=None)
    )
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
    gateway = AutonomousModelGateway(
        ModelConfig(endpoint="", model="test", api_key=None)
    )

    assert gateway._deterministic_file_creation(
        "Create a new file named src/unsafe.py containing the current repository name"
    ) is None
    assert gateway._deterministic_file_creation(
        "Create a new file named .github/workflows/unsafe.md containing the current repository name"
    ) is None
