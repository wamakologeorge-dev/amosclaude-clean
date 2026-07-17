from amoscloud_ai.agent.interaction_orchestrator import (
    InteractionIntent,
    InteractionSession,
    PlanStep,
    WorkState,
    apply_interaction,
    recognize_interaction_intent,
    welcoming_message,
)


def test_welcome_makes_user_control_and_transparency_clear():
    reply = welcoming_message("George")

    assert "Welcome George" in reply
    assert "project partner" in reply
    assert "show the plan before execution" in reply
    assert "mirror panel" in reply
    assert "pause" in reply
    assert reply.count("?") == 1


def test_user_can_pause_active_work_and_keep_conversing():
    session = InteractionSession(objective="Build a restaurant ordering platform", state=WorkState.EXECUTING)

    reply = apply_interaction(session, "Pause the job")

    assert recognize_interaction_intent("Pause the job") == InteractionIntent.PAUSE
    assert session.state == WorkState.PAUSED
    assert "Nothing else will be changed" in reply
    assert "ask questions or add ideas" in reply


def test_user_can_stop_without_losing_project_context():
    session = InteractionSession(objective="Repair the dashboard", state=WorkState.EXECUTING)

    reply = apply_interaction(session, "Stop the job")

    assert session.state == WorkState.STOPPED
    assert session.objective == "Repair the dashboard"
    assert "preserved" in reply
    assert "evidence" in reply


def test_added_idea_is_preserved_and_not_silently_executed():
    session = InteractionSession(objective="Build a business website", state=WorkState.EXECUTING)

    reply = apply_interaction(
        session,
        "Add this idea to the project",
        idea="Allow customers to schedule consultations",
    )

    assert session.ideas == ["Allow customers to schedule consultations"]
    assert session.state == WorkState.EXECUTING
    assert "Before changing active work" in reply
    assert "show where it fits" in reply


def test_plan_is_shown_as_readable_steps_before_execution():
    session = InteractionSession(
        objective="Build an AI agent",
        plan=[
            PlanStep(1, "Understand the goal", "Confirm the users and expected outcome", "completed"),
            PlanStep(2, "Design the system", "Choose components and safety boundaries", "active"),
            PlanStep(3, "Implement and verify", "Build in small testable changes"),
        ],
    )

    reply = apply_interaction(session, "Show me the plan")

    assert "1. Understand the goal" in reply
    assert "2. Design the system" in reply
    assert "3. Implement and verify" in reply
    assert "pause" in reply
    assert "add an idea" in reply


def test_mirror_panel_update_has_normal_reading_sequence_and_controls():
    session = InteractionSession(objective="Build a website", state=WorkState.EXECUTING)
    first = session.add_mirror_event(
        phase="implementation",
        title="Creating the navigation component",
        explanation="Adding the primary routes defined in the approved plan.",
        evidence=("web/navigation.js",),
    )
    second = session.add_mirror_event(
        phase="verification",
        title="Checking navigation behavior",
        explanation="Running focused tests before moving to the next component.",
        evidence=("tests/test_navigation.py", "3 tests passed"),
    )

    assert first.sequence == 1
    assert second.sequence == 2
    assert "pause" in second.user_action_available
    assert "ask" in second.user_action_available
    assert "add idea" in second.user_action_available
    assert "stop" in second.user_action_available

    reply = apply_interaction(session, "Show progress")
    assert "Current phase: verification" in reply
    assert "normal reading speed" in reply


def test_user_can_ask_to_see_how_the_project_is_built():
    session = InteractionSession(objective="Build a mobile app")

    reply = apply_interaction(session, "Demonstrate how it is built")

    assert "approved plan" in reply
    assert "reason for each change" in reply
    assert "verification result" in reply
    assert "mirror-panel updates" in reply


def test_agent_offers_alternative_path_with_tradeoffs_and_user_choice():
    session = InteractionSession(objective="Deploy an API")

    reply = apply_interaction(session, "Is there another path?")

    assert recognize_interaction_intent("Is there another path?") == InteractionIntent.EXPLORE_ALTERNATIVE
    assert "trade-offs" in reply
    assert "risk" in reply
    assert "maintainability" in reply
    assert "ask whether" in reply


def test_normal_conversation_does_not_require_a_build_command():
    session = InteractionSession(objective="Explore a business idea")

    reply = apply_interaction(session, "I am not sure this is the right approach")

    assert recognize_interaction_intent("I am not sure this is the right approach") == InteractionIntent.CONVERSE
    assert "talk with me normally" in reply
    assert "ask why" in reply
    assert "another path" in reply


def test_stopped_job_requires_a_fresh_plan_before_restart():
    session = InteractionSession(objective="Refactor the API", state=WorkState.STOPPED)

    reply = apply_interaction(session, "Continue")

    assert session.state == WorkState.STOPPED
    assert "new plan" in reply
    assert "before restarting" in reply
