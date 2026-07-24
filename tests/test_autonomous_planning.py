from amosclaud_bot.autonomous_planning import (
    decode_plan_marker,
    format_plan,
    is_continue_request,
    latest_plan,
    plan_steps,
)


def test_continue_language_is_recognized():
    assert is_continue_request("@amosclaud continue") is True
    assert is_continue_request("@amosclaud-bot finish the remaining work.") is True
    assert is_continue_request("@amosclaud create a health check") is False


def test_write_plan_contains_real_execution_gates():
    steps = plan_steps("fix")
    assert any("modify" in step.lower() for step in steps)
    assert any("tests" in step.lower() for step in steps)
    assert any("pull request" in step.lower() for step in steps)


def test_plan_marker_round_trips_objective():
    body = format_plan("fix", "create a repository health check")
    assert "Autonomous Plan" in body
    assert "Proceeding through the existing approval" in body
    assert decode_plan_marker(body) == {
        "command": "fix",
        "objective": "create a repository health check",
    }


def test_latest_plan_uses_most_recent_issue_memory():
    old = format_plan("inspect", "inspect the repository")
    new = format_plan("fix", "repair the failing CI test")
    assert latest_plan([{"body": old}, {"body": "ordinary comment"}, {"body": new}]) == {
        "command": "fix",
        "objective": "repair the failing CI test",
    }


def test_invalid_marker_is_ignored():
    assert decode_plan_marker("<!-- amosclaud-autonomous-plan:{bad json} -->") is None
    assert latest_plan([{"body": "no plan here"}]) is None
