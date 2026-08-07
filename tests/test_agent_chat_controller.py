from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def load_agent_chat():
    path = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "agent_chat.py"
    spec = importlib.util.spec_from_file_location("amosclaud_agent_chat", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def agent_chat():
    return load_agent_chat()


def test_redaction_removes_credentials(agent_chat):
    value = "Authorization: Basic placeholder\napi_key=placeholder-value"
    redacted = agent_chat.redact(value)
    assert "Basic placeholder" not in redacted
    assert "placeholder-value" not in redacted
    assert "[REDACTED]" in redacted


@pytest.mark.parametrize(
    ("log_text", "category"),
    [
        ("would reformat module.py", "formatting"),
        ("forbidden root artifacts: package.zip", "repository-cleanliness"),
        ("AssertionError\npytest failed", "test-failure"),
        ("Resource not accessible by integration", "permissions"),
    ],
)
def test_deterministic_failure_classification(agent_chat, log_text, category):
    diagnosis = agent_chat.diagnose(
        conclusion="failure", failed_jobs=["verify"], log_text=log_text
    )
    assert diagnosis.category == category
    assert diagnosis.repairable is True


def test_startup_failure_is_not_sent_to_code_fixer(agent_chat):
    diagnosis = agent_chat.diagnose(
        conclusion="startup_failure", failed_jobs=[], log_text=""
    )
    assert diagnosis.category == "workflow-startup"
    assert diagnosis.repairable is False


def test_comment_never_claims_tests_were_replaced(agent_chat):
    diagnosis = agent_chat.diagnose(
        conclusion="failure",
        failed_jobs=["fast-pr-gate"],
        log_text="would reformat module.py",
    )
    result = agent_chat.DoctorResult(
        workflow_name="Fast PR Gate",
        conclusion="failure",
        run_id=123,
        run_attempt=1,
        target_sha="abc123",
        pull_request_number=7,
        diagnosis=diagnosis,
        repair_requested=True,
    )
    rendered = agent_chat.render_comment(result)
    assert "Repair requested: `true`" in rendered
    assert "Repository tests run independently" in rendered
    assert "dispatched for this exact revision" in rendered


def test_green_result_requires_all_checks_complete(agent_chat, monkeypatch):
    monkeypatch.setattr(
        agent_chat,
        "api_json",
        lambda *_args, **_kwargs: {
            "check_runs": [
                {
                    "name": "Fast PR Gate",
                    "status": "completed",
                    "conclusion": "success",
                },
                {
                    "name": "Python package",
                    "status": "completed",
                    "conclusion": "success",
                },
            ]
        },
    )
    all_green, failing, pending = agent_chat.summarize_sha("token", "owner/repo", "abc")
    assert all_green is True
    assert failing == []
    assert pending == []
