from amoscloud_ai.api.routes import agent


def test_autonomous_identity_uses_agent_wording():
    assert agent.AGENT_NAME == "Amosclaud Autonomous Agent"
    assert "autonomous" in agent.AGENT_ROLE
    assert "agent" in agent.AGENT_ROLE
    assert agent.AGENT_MODE == "agent"


def test_fix_mode_enables_controlled_agent_changes():
    execution_mode, metadata = agent._agent_metadata("fix", {})

    assert execution_mode == "build"
    assert metadata["requested_mode"] == "fix"
    assert metadata["use_agent"] is True
    assert metadata["apply_changes"] is True
    assert metadata["phases"] == ["understand", "inspect", "plan", "act", "verify", "report"]


def test_build_mode_is_plan_only_by_default():
    execution_mode, metadata = agent._agent_metadata("build", {})

    assert execution_mode == "build"
    assert metadata["use_agent"] is True
    assert metadata["apply_changes"] is False
