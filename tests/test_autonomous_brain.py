from amoscloud_ai.autonomous_learning_academy import LessonCandidate
from amosclaud_bot.autonomous_brain import GitHubAutonomousBrain


def test_brain_reuses_verified_memory_academy_and_curriculum(tmp_path, monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_AUTONOMOUS_LEVEL", "3200")
    brain = GitHubAutonomousBrain(tmp_path, "Owner/Repo")
    brain.memory.remember(
        kind="github-bot-fix",
        title="Verified workflow repair",
        content="Install pytest before running the test job.",
        tags=["github-actions", "pytest"],
        project="owner/repo",
        confidence=0.9,
        outcome="success",
    )
    brain.memory.remember(
        kind="github-bot-fix",
        title="Failed broad dependency rewrite",
        content="Do not rewrite every dependency file for one missing CI module.",
        tags=["github-actions", "failure"],
        project="owner/repo",
        confidence=0.8,
        outcome="failure",
    )
    brain.academy.submit_verified_lesson(
        LessonCandidate(
            title="Repair missing pytest in the invoking workflow",
            problem_signature="No module named pytest in GitHub Actions",
            root_cause="The workflow invokes pytest without installing it.",
            resolution="Add pytest to the existing workflow install command.",
            verification="The targeted workflow and pytest suite passed.",
            source_type="verified-fix",
            source_reference="pull/524",
            target_agents=(2, 3, 4, 5),
            tags=("github-actions", "pytest"),
        ),
        auto_approve=True,
    )

    context = brain.prepare("fix", "repair missing pytest in GitHub Actions")

    assert context["source"] == "amosclaud-github-actions-bot"
    assert context["current_level"] == 3200
    assert context["current_curriculum"]["track"] == "data-memory-models"
    assert context["proven_memories"][0]["outcome"] == "success"
    assert context["failed_attempts_to_avoid"][0]["outcome"] == "failure"
    assert context["approved_lessons"][0]["source_reference"] == "pull/524"
    assert {item["id"] for item in context["agent_roles"]} == {2, 3, 4, 5}


def test_brain_records_verified_and_unverified_results_truthfully(tmp_path):
    brain = GitHubAutonomousBrain(tmp_path, "owner/repo")

    verified = brain.observe(
        "verify",
        "verify the repair",
        {"status": "completed", "evidence": ["pytest passed"], "changed_files": []},
        source_run_id="run-1",
    )
    unverified = brain.observe(
        "fix",
        "attempt a repair",
        {"status": "completed", "evidence": [], "changed_files": ["app.py"]},
        source_run_id="run-2",
    )
    failed = brain.observe(
        "fix",
        "attempt a broken repair",
        {"status": "failed", "error": "tests failed", "evidence": []},
        source_run_id="run-3",
    )

    assert verified["outcome"] == "success"
    assert unverified["outcome"] == "partial"
    assert failed["outcome"] == "failure"
    assert brain.memory.stats()["memories"] == 3


def test_brain_never_uses_memory_as_authorization(tmp_path):
    brain = GitHubAutonomousBrain(tmp_path, "owner/repo")
    context = brain.prepare("fix", "change a workflow")

    assert any("never as proof" in rule.lower() for rule in context["rules"])
    assert any("grant write authority" in rule.lower() for rule in context["rules"])
