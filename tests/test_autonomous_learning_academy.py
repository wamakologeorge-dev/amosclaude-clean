from amoscloud_ai.autonomous_learning_academy import (
    AcademyError,
    AutonomousLearningAcademy,
    LessonCandidate,
    verified_fix_lesson,
)


def test_verified_lesson_teaches_matching_agent(tmp_path):
    academy = AutonomousLearningAcademy(tmp_path / "academy.db")
    lesson = academy.submit_verified_lesson(
        verified_fix_lesson(
            title="Repair owner authorization mismatch",
            problem_signature="administrator can open admin dashboard but runtime says owner required",
            root_cause="runtime used a different owner decision than the admin dashboard",
            resolution="use one founder identity decision for runtime and autonomous",
            tests=["owner status test passed", "runtime authorization test passed"],
            source_reference="PR-252",
            tags=("owner", "authorization", "runtime"),
        ),
        auto_approve=True,
    )

    context = academy.build_teacher_context("runtime owner authorization required", agent_id=3)
    assert lesson["status"] == "approved"
    assert context["agent_role"] == "plan-with-model"
    assert context["lessons"][0]["id"] == lesson["id"]


def test_untrusted_or_unverified_lesson_is_rejected(tmp_path):
    academy = AutonomousLearningAcademy(tmp_path / "academy.db")
    candidate = LessonCandidate(
        title="Guess",
        problem_signature="unknown failure",
        root_cause="maybe network",
        resolution="restart everything",
        verification="",
        source_type="agent-opinion",
        source_reference="",
    )

    try:
        academy.submit_verified_lesson(candidate)
    except AcademyError as exc:
        assert "trusted" in str(exc) or "verification" in str(exc)
    else:
        raise AssertionError("Unverified lesson was accepted")


def test_approval_assigns_lesson_and_records_progress(tmp_path):
    academy = AutonomousLearningAcademy(tmp_path / "academy.db")
    lesson = academy.submit_verified_lesson(
        LessonCandidate(
            title="Handle model connection refusal",
            problem_signature="model endpoint connection refused",
            root_cause="model process is not listening",
            resolution="probe readiness before agent planning and report a precise blocker",
            verification="readiness tests passed",
            source_type="passing-test",
            source_reference="tests/test_agent_readiness.py",
            target_agents=(2, 3, 5),
            tags=("model", "network", "readiness"),
        )
    )
    academy.approve_lesson(lesson["id"], evidence="reviewed passing readiness tests")
    result = academy.complete_lesson(3, lesson["id"], score=92, evidence="planned using readiness preflight")
    status = academy.classroom_status()

    assert result["status"] == "completed"
    assert status["lessons"]["approved"] == 1
    assert status["agents"][3]["completed"] == 1
