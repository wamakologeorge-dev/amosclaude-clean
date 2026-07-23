import pytest

from amosclaud_bot.intelligence_router import parse_intelligence_command
from amosclaud_bot.mission_ledger import (
    advance_task,
    block_task,
    build_mission,
    decode_mission_marker,
    encode_mission_marker,
    parse_mission_request,
    recover_mission,
    render_mission,
)


def test_goal_and_mission_commands_route_to_v4_ledger():
    assert parse_intelligence_command("@amosclaud mission repair authentication") == (
        "mission",
        "repair authentication",
    )
    assert parse_intelligence_command("@amosclaud goal repair authentication") == (
        "goal",
        "repair authentication",
    )
    assert parse_mission_request("@amosclaud mission status") == ("status", "", "")
    assert parse_mission_request("@amosclaud goal recover") == ("recover", "", "")


def test_mission_marker_round_trip_preserves_dependencies_and_budgets():
    mission = build_mission("Repair authentication and verify CI")
    restored = decode_mission_marker(encode_mission_marker(mission))

    assert restored is not None
    assert restored.mission_id == mission.mission_id
    assert restored.objective == mission.objective
    assert restored.tasks[1].depends_on == [restored.tasks[0].task_id]
    assert restored.budgets["max_repair_attempts"] == 3


def test_task_cannot_advance_without_evidence_or_verified_dependencies():
    mission = build_mission("Repair authentication")

    with pytest.raises(ValueError, match="evidence"):
        advance_task(mission, mission.tasks[0].task_id, "")

    with pytest.raises(ValueError, match="dependencies"):
        advance_task(mission, mission.tasks[1].task_id, "inspection passed")

    advance_task(mission, mission.tasks[0].task_id, "triage report recorded")
    advance_task(mission, mission.tasks[1].task_id, "repository inspection passed")

    assert mission.tasks[1].status == "verified"
    assert mission.last_verified_task == mission.tasks[1].task_id
    assert mission.confidence > 0.5


def test_block_and_recover_resume_after_last_verified_checkpoint():
    mission = build_mission("Repair authentication")
    advance_task(mission, mission.tasks[0].task_id, "triage verified")
    block_task(mission, mission.tasks[1].task_id, "integration logs unavailable")

    assert mission.status == "blocked"
    assert mission.tasks[1].status == "blocked"

    recover_mission(mission)

    assert mission.status == "active"
    assert mission.tasks[0].status == "verified"
    assert mission.tasks[1].status == "pending"
    assert mission.tasks[1].blocker == ""


def test_rendered_ledger_exposes_progress_confidence_budget_and_marker():
    mission = build_mission("Repair authentication")
    advance_task(mission, mission.tasks[0].task_id, "triage verified")
    body = render_mission(mission)

    assert "Multi-Task Mission Ledger" in body
    assert "Confidence" in body
    assert "Execution budget" in body
    assert "Last verified checkpoint" in body
    assert "amosclaud-mission-ledger" in body
