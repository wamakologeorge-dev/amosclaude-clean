from amoscloud_ai.agent.conversation_intelligence import (
    Intent,
    OutputTarget,
    analyze_message,
    build_guided_reply,
)


def test_explanation_stays_in_chat_without_repository_permission():
    decision = analyze_message("Explain what this authentication code does.")

    assert decision.intent == Intent.EXPLAIN
    assert decision.output_target == OutputTarget.CHAT
    assert decision.execution_requested is False
    assert decision.repository_changes_allowed is False
    assert decision.explanation_requested is True


def test_code_example_with_no_edit_instruction_never_executes():
    decision = analyze_message(
        "Show me code for a FastAPI middleware, but do not edit the repository."
    )

    assert decision.intent == Intent.SHOW_EXAMPLE
    assert decision.output_target == OutputTarget.CHAT
    assert decision.execution_requested is False
    assert decision.repository_changes_allowed is False


def test_repository_change_without_clear_execution_requires_clarification():
    decision = analyze_message("Write authentication middleware for the project.")

    assert decision.intent == Intent.CHANGE_REPOSITORY
    assert decision.clarification_required is True
    assert decision.repository_changes_allowed is False
    assert "edit the repository" in decision.clarification_question


def test_explicit_change_request_can_authorize_repository_work():
    decision = analyze_message(
        "Add authentication middleware to the repository and make the changes."
    )

    assert decision.intent == Intent.CHANGE_REPOSITORY
    assert decision.output_target == OutputTarget.REPOSITORY
    assert decision.execution_requested is True
    assert decision.repository_changes_allowed is True
    assert decision.clarification_required is False


def test_conflicting_deployment_instruction_is_blocked():
    decision = analyze_message("Deploy it now, but do not deploy anything yet.")

    assert decision.intent == Intent.UNKNOWN
    assert decision.clarification_required is True
    assert decision.execution_requested is False
    assert decision.repository_changes_allowed is False
    assert decision.contradictions


def test_short_follow_up_resumes_previous_objective():
    decision = analyze_message(
        "Proceed",
        previous_objective="Build the restaurant website",
    )

    assert decision.intent == Intent.RESUME
    assert decision.output_target == OutputTarget.REPOSITORY
    assert decision.execution_requested is True
    assert decision.repository_changes_allowed is True
    assert decision.previous_objective == "Build the restaurant website"


def test_natural_resume_phrases_preserve_previous_objective():
    for message in (
        "Continue",
        "Resume",
        "Keep going",
        "Proceed where we left off",
        "Continue where we left off",
    ):
        decision = analyze_message(message, previous_objective="Repair the dashboard")
        assert decision.intent == Intent.RESUME
        assert decision.repository_changes_allowed is True
        assert decision.clarification_required is False


def test_resume_without_context_asks_for_the_unfinished_task():
    decision = analyze_message("Continue")

    assert decision.intent == Intent.RESUME
    assert decision.execution_requested is False
    assert decision.repository_changes_allowed is False
    assert decision.clarification_required is True
    assert "unfinished task" in decision.clarification_question


def test_capability_question_educates_before_asking_one_follow_up():
    decision = analyze_message("What can you create?")
    reply = build_guided_reply(decision)

    assert decision.intent == Intent.DISCOVER_CAPABILITIES
    assert decision.output_target == OutputTarget.CHAT
    assert decision.execution_requested is False
    assert decision.repository_changes_allowed is False
    assert "websites" in reply
    assert "mobile apps" in reply
    assert "AI agents" in reply
    assert "repository" in reply
    assert reply.count("?") == 1


def test_project_idea_turns_uncertainty_into_a_meaningful_question():
    decision = analyze_message("I have an idea")
    reply = build_guided_reply(decision)

    assert decision.intent == Intent.PROJECT_IDEA
    assert decision.execution_requested is False
    assert "complete plan" in reply
    assert "What problem" in reply
    assert reply.count("?") == 1


def test_random_question_is_answered_in_chat_not_treated_as_execution():
    decision = analyze_message("How can an AI agent help a small business?")

    assert decision.intent == Intent.GENERAL_QUESTION
    assert decision.output_target == OutputTarget.CHAT
    assert decision.execution_requested is False
    assert decision.repository_changes_allowed is False
    assert decision.clarification_required is False


def test_guided_resume_reply_restores_the_objective():
    decision = analyze_message(
        "Proceed where we left off",
        previous_objective="Create a restaurant ordering platform",
    )
    reply = build_guided_reply(decision, user_name="George")

    assert "Create a restaurant ordering platform" in reply
    assert "next unfinished step" in reply


def test_mixed_conversation_is_split_into_topics():
    decision = analyze_message(
        "Build a restaurant website. Also explain Python decorators. "
        "Now show me a decorator example in chat only."
    )

    assert len(decision.topics) >= 2
    assert decision.repository_changes_allowed is False
    assert decision.explanation_requested is True
