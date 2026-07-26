from __future__ import annotations

import re
from pathlib import Path

import yaml


WORKFLOW = Path(".github/workflows/cmood_agent_trigger.yml")


def _workflow_steps() -> list[dict[str, object]]:
    parsed = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    jobs = parsed.get("jobs")
    assert isinstance(jobs, dict)
    job = jobs.get("run_cmood_agent")
    assert isinstance(job, dict)
    steps = job.get("steps")
    assert isinstance(steps, list)
    return [step for step in steps if isinstance(step, dict)]


def _uses_exact_immutable_pin(action: str) -> bool:
    expected = re.compile(rf"^{re.escape(action)}@[0-9a-f]{{40}}$")
    return any(
        isinstance(step.get("uses"), str)
        and expected.fullmatch(str(step["uses"])) is not None
        for step in _workflow_steps()
    )


def test_cmood_workflow_uses_pinned_actions_and_safe_install_path() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert _uses_exact_immutable_pin("actions/checkout")
    assert _uses_exact_immutable_pin("actions/setup-python")
    assert "cd cmood" in text
    assert "python -m pip install --disable-pip-version-check -r requirements.txt" in text
    assert 'python -c "import cmood.agent;' in text


def test_cmood_workflow_yaml_is_valid() -> None:
    parsed = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    assert "jobs" in parsed
    assert "run_cmood_agent" in parsed["jobs"]
