from amosclaud_bot.autonomous_brain import GitHubAutonomousBrain
from amosclaud_bot.github_intelligence import (
    classify_issue,
    decode_goal_marker,
    encode_goal_marker,
    latest_goal,
    render_goal,
)
from amosclaud_bot.intelligence_router import parse_intelligence_command


def test_v3_commands_are_routed_without_changing_core_bot_parser():
    assert parse_intelligence_command("@amosclaud triage") == ("triage", "")
    assert parse_intelligence_command("@amosclaud health repository") == (
        "health",
        "repository",
    )
    assert parse_intelligence_command("@amosclaud goal repair all failing workflows") == (
        "goal",
        "repair all failing workflows",
    )
    assert parse_intelligence_command("@amosclaud fix CI") == (None, "")


def test_issue_triage_assigns_priority_labels_and_agent_roles():
    triage = classify_issue(
        {
            "title": "Security workflow fails to validate token permissions",
            "body": "The CI pipeline has a regression and the authentication test fails.",
        }
    )

    assert triage["priority"] == "P0"
    assert triage["risk"] == "high"
    assert "security" in triage["suggested_labels"]
    assert "ci" in triage["suggested_labels"]
    assert "bug" in triage["suggested_labels"]
    assert triage["private_review_recommended"] is True
    assert triage["agent_roles"][-1] == "Verify and report"


def test_goal_markers_persist_multi_task_objective_in_github_comments():
    marker = encode_goal_marker("Improve repository health", completed=2)
    decoded = decode_goal_marker(marker)

    assert decoded == {"objective": "Improve repository health", "completed": 2}
    assert latest_goal([{"body": "old"}, {"body": marker}]) == decoded
    rendered = render_goal(decoded["objective"], completed=decoded["completed"])
    assert "33%" in rendered
    assert rendered.count("🟩") == 2
    assert "amosclaud-autonomous-goal" in rendered


def test_brain_v3_reuses_rollimage_connectors_and_safe_cross_repo_policy(tmp_path):
    brain = GitHubAutonomousBrain(tmp_path, "owner/repo")
    context = brain.prepare("goal", "Coordinate a multi-repository verified repair")

    assert context["rollimage"]["intent"] == "Coordinate a multi-repository verified repair"
    assert context["rollimage"]["next_actions"] == [
        "Understand",
        "Inspect",
        "Plan",
        "Act when authorized",
        "Verify",
        "Report",
    ]
    assert "clone" in context["connector_capabilities"]
    assert "remote" in context["connector_capabilities"]
    assert any("approved academy lessons" in rule.lower() for rule in context["cross_repository_policy"])
    assert any("never transfer secrets" in rule.lower() for rule in context["cross_repository_policy"])
