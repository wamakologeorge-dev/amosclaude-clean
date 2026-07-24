from amoscloud_ai.agent.interaction_orchestrator import (
    InteractionIntent,
    InteractionSession,
    PlanStep,
    WorkState,
    apply_interaction,
    recognize_interaction_intent,
    welcoming_message,
)


def test_welcome_promises_continuity_transparency_and_user_control():
    reply = welcoming_message("George")

    assert "Welcome George" in reply
    assert "project partner" in reply
    assert "right project path" in reply
    assert "show the plan before execution" in reply
    assert "mirror panel" in reply
    assert "never ends our conversation" in reply
    assert reply.count("?") == 1


def test_user_can_pause_work_without_pausing_the_conversation():
    session = InteractionSession(objective="Build a restaurant ordering platform", state=WorkState.EXECUTING)

    reply = apply_interaction(session, "Pause the job")

    assert recognize_interaction_intent("Pause the job") == InteractionIntent.PAUSE
    assert session.state == WorkState.PAUSED
    assert session.conversation_open is True
    assert "conversation remains open" in reply
    assert "review the plan" in reply
    assert "explore another path" in reply


def test_stopping_work_never_ends_the_project_conversation():
    session = InteractionSession(objective="Repair the dashboard", state=WorkState.EXECUTING)

    reply = apply_interaction(session, "Stop the job")

    assert recognize_interaction_intent("Stop the job") == InteractionIntent.STOP_WORK
    assert session.state == WorkState.WORK_STOPPED
    assert session.conversation_open is True
    assert session.objective == "Repair the dashboard"
    assert "not our conversation" in reply
    assert "preserved" in reply
    assert "another path" in reply


def test_resume_after_stopped_work_continues_same_objective():
    session = InteractionSession(objective="Refactor the API", state=WorkState.WORK_STOPPED)

    reply = apply_interaction(session, "Continue")

    assert session.state == WorkState.EXECUTING
    assert session.conversation_open is True
    assert "Refactor the API" in reply
    assert "next unfinished approved step" in reply
    assert "same project path" in reply


def test_added_idea_stays_on_active_project_path_without_silent_execution():
    session = InteractionSession(objective="Build a business website", state=WorkState.EXECUTING)

    reply = apply_interaction(
        session,
        "Add this idea to the project",
        idea="Allow customers to schedule consultations",
    )

    assert session.ideas == ["Allow customers to schedule consultations"]
    assert session.state == WorkState.EXECUTING
    assert session.conversation_open is True
    assert "active project conversation" in reply
    assert "before any execution changes" in reply


def test_plan_is_shown_as_readable_project_path():
    session = InteractionSession(
        objective="Build an AI agent",
        plan=[
            PlanStep(1, "Understand the goal", "Confirm the users and expected outcome", "completed"),
            PlanStep(2, "Design the system", "Choose components and safety boundaries", "active"),
            PlanStep(3, "Implement and verify", "Build in small testable changes"),
        ],
    )

    reply = apply_interaction(session, "Show me the plan")

    assert "current project path" in reply
    assert "1. Understand the goal" in reply
    assert "2. Design the system" in reply
    assert "3. Implement and verify" in reply
    assert "We remain on this conversation path" in reply


def test_mirror_panel_uses_readable_sequence_and_keeps_conversation_active():
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
    assert "pause work" in second.user_action_available
    assert "ask a question" in second.user_action_available
    assert "add idea" in second.user_action_available
    assert "change direction" in second.user_action_available
    assert "stop work" in second.user_action_available

    reply = apply_interaction(session, "Show progress")
    assert "Current phase: verification" in reply
    assert "normal reading speed" in reply
    assert "conversation remains active" in reply


def test_user_can_see_exactly_how_the_project_is_being_built():
    session = InteractionSession(objective="Build a mobile app")

    reply = apply_interaction(session, "Demonstrate how it is built")

    assert "agreed plan" in reply
    assert "why each change is needed" in reply
    assert "verification result" in reply
    assert "next conversation step" in reply
    assert "mirror-panel updates" in reply


def test_agent_compares_another_path_without_losing_current_path():
    session = InteractionSession(objective="Deploy an API")

    reply = apply_interaction(session, "Is there another path?")

    assert recognize_interaction_intent("Is there another path?") == InteractionIntent.EXPLORE_ALTERNATIVE
    assert "without losing the current one" in reply
    assert "trade-offs" in reply
    assert "risk" in reply
    assert "maintainability" in reply
    assert "whichever path you approve" in reply


def test_normal_conversation_is_connected_to_the_active_objective():
    session = InteractionSession(objective="Explore a business idea")

    reply = apply_interaction(session, "I am not sure this is the right approach")

    assert recognize_interaction_intent("I am not sure this is the right approach") == InteractionIntent.CONVERSE
    assert "Explore a business idea" in reply
    assert "speak with me naturally" in reply
    assert "right project path" in reply
    assert "instead of ending the conversation" in reply
