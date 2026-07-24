from src.agent.cloud_agent import AmosclaudCloudAgent


def test_agent_assistant_explains_plan_risks_and_solution(monkeypatch):
    agent = AmosclaudCloudAgent()
    monkeypatch.setattr(agent.model, "available", lambda: False)
    reply = agent.reply("Plan how to fix login safely")
    assert reply.instruction_detected is True
    assert reply.requires_authorization is True
    assert reply.plan
    assert reply.what_can_go_wrong
    assert reply.recommended_solution
    assert reply.easier_way
    assert "authorization" in reply.next_step.lower()


def test_agent_assistant_points_to_internal_and_external_results(monkeypatch):
    agent = AmosclaudCloudAgent()
    monkeypatch.setattr(agent.model, "available", lambda: False)
    reply = agent.reply(
        "Review the result",
        result_locations=["/agent-mission-control", "https://github.com/example/repo/pull/1"],
    )
    locations = {item.location for item in reply.result_pointers}
    assert "/agent-mission-control" in locations
    assert "https://github.com/example/repo/pull/1" in locations
    assert {item.kind for item in reply.result_pointers} == {"internal", "external"}


def test_agent_assistant_does_not_execute_write_without_authorization(monkeypatch):
    agent = AmosclaudCloudAgent()
    monkeypatch.setattr(agent.model, "available", lambda: False)
    reply = agent.reply("Fix the login code", execute=True, authorized_writes=False)
    assert reply.execution_result is None
    assert reply.requires_authorization is True
    assert "waiting" in reply.reply.lower()
