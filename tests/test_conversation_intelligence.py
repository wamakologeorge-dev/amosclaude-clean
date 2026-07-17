from amoscloud_ai.agent.conversation_intelligence import (
    Intent,
    OutputTarget,
    analyze_message,
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


def test_short_follow_up_uses_previous_objective():
    decision = analyze_message(
        "Proceed",
        previous_objective="Build the restaurant website",
    )

    assert decision.intent == Intent.CHANGE_REPOSITORY
    assert decision.execution_requested is True
    assert decision.repository_changes_allowed is True


def test_mixed_conversation_is_split_into_topics():
    decision = analyze_message(
        "Build a restaurant website. Also explain Python decorators. "
        "Now show me a decorator example in chat only."
    )

    assert len(decision.topics) >= 2
    assert decision.repository_changes_allowed is False
    assert decision.explanation_requested is True
