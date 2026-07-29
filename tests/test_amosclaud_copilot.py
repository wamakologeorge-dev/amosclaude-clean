"""Tests for the repository-aware Amosclaud Copilot coordinator."""

import pytest

from amoscloud_ai.copilot import (
    available_agents,
    build_copilot_plan,
    copilot_profile,
    pipeline_reply,
)
from amoscloud_ai.models import PipelineStatus


def test_copilot_profile_exposes_all_agent_routes():
    profile = copilot_profile()

    assert profile["id"] == "amosclaud-copilot"
    assert profile["name"] == "Amosclaud Copilot"
    assert profile["endpoints"]["run"] == "/api/v1/copilot/run"
    assert {agent["name"] for agent in profile["agents"]} == {
        agent["name"] for agent in available_agents()
    }


def test_bug_request_routes_to_fixer_and_autonomous_support():
    plan = build_copilot_plan(
        "Fix the failing repository API test and verify the regression",
        repository="wamakologeorge-dev/amosclaude-clean",
        file_path="tests/test_server.py",
        language="python",
    )

    assert plan["primary_agent"]["name"] == "amosclaud-fixer"
    assert plan["execution_mode"] == "fix"
    assert "amosclaud-autonomous" in {
        agent["name"] for agent in plan["supporting_agents"]
    }
    assert plan["handoff"]["payload"]["metadata"]["copilot_primary_agent"] == "amosclaud-fixer"


def test_security_request_routes_to_security_agent():
    plan = build_copilot_plan(
        "Review authentication permissions and token handling for vulnerabilities"
    )

    assert plan["primary_agent"]["name"] == "amosclaud-security"
    assert plan["execution_mode"] == "autonomous-check"


def test_explicit_agent_alias_overrides_keyword_routing():
    plan = build_copilot_plan(
        "Explain why this test is failing",
        requested_agent="codex",
    )

    assert plan["primary_agent"]["name"] == "amosclaud-codex-agent"


def test_repository_path_cannot_escape_workspace():
    with pytest.raises(ValueError, match="inside the repository"):
        build_copilot_plan("Explain this file", file_path="../../etc/passwd")


def test_existing_pipeline_reply_contract_remains_compatible():
    assert pipeline_reply(PipelineStatus.PENDING).startswith("Amosclaud Autonomous Server:")
