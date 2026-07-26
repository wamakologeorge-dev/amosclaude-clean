from __future__ import annotations

import re
from pathlib import Path

import yaml


WORKFLOW = Path(".github/workflows/cmood_agent_trigger.yml")


def _is_immutable_action_pin(text: str, action: str) -> bool:
    pattern = rf"uses:\s*{re.escape(action)}@([0-9a-f]{{40}})"
    return re.search(pattern, text) is not None


def test_cmood_workflow_uses_pinned_actions_and_safe_install_path() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert _is_immutable_action_pin(text, "actions/checkout")
    assert _is_immutable_action_pin(text, "actions/setup-python")
    assert "cd cmood" in text
    assert "python -m pip install --disable-pip-version-check -r requirements.txt" in text
    assert 'python -c "import cmood.agent;' in text


def test_cmood_workflow_yaml_is_valid() -> None:
    parsed = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    assert "jobs" in parsed
    assert "run_cmood_agent" in parsed["jobs"]
