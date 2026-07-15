from amoscloud_ai.api.routes import agent


def test_autonomous_runtime_identity_uses_runtime_wording():
    assert agent.AGENT_NAME == "Amosclaud Autonomous Runtime"
    assert agent.AGENT_ROLE == "autonomous build, deployment, and monitoring runtime"
    assert "Server" not in agent.AGENT_NAME
    assert "server" not in agent.AGENT_ROLE
