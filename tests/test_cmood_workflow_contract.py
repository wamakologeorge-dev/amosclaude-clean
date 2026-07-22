from __future__ import annotations

from pathlib import Path

import yaml


WORKFLOW = Path('.github/workflows/cmood_agent_trigger.yml')


def test_cmood_workflow_uses_pinned_actions_and_safe_install_path() -> None:
    text = WORKFLOW.read_text(encoding='utf-8')

    assert 'actions/checkout@11d5960a326750d5838078e36cf38b85af677262' in text
    assert 'actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065' in text
    assert 'cd cmood' in text
    assert 'python -m pip install --disable-pip-version-check -r requirements.txt' in text
    assert 'python -c "import cmood.agent;' in text


def test_cmood_workflow_yaml_is_valid() -> None:
    parsed = yaml.safe_load(WORKFLOW.read_text(encoding='utf-8'))
    assert isinstance(parsed, dict)
    assert 'jobs' in parsed
    assert 'run_cmood_agent' in parsed['jobs']
