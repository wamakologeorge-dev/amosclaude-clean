from amoscloud_ai.autonomous_server import _conversation_gate


def test_build_without_clear_authorization_is_blocked():
    check, metadata = _conversation_gate(
        "build",
        "Write authentication middleware for the project.",
        {},
    )

    assert check.status == "failed"
    assert metadata["repository_changes_allowed"] is False
    assert metadata["clarification_required"] is True


def test_explicit_repository_change_is_allowed():
    check, metadata = _conversation_gate(
        "build",
        "Add authentication middleware to the repository and make the changes.",
        {},
    )

    assert check.status == "passed"
    assert metadata["repository_changes_allowed"] is True
    assert metadata["execution_requested"] is True


def test_contradictory_deployment_is_blocked():
    check, metadata = _conversation_gate(
        "deploy",
        "Deploy it now, but do not deploy anything yet.",
        {},
    )

    assert check.status == "failed"
    assert metadata["contradictions"]


def test_inspection_mode_records_intent_without_write_authorization():
    check, metadata = _conversation_gate(
        "autonomous-check",
        "Inspect the failing Python test.",
        {},
    )

    assert check.status == "passed"
    assert metadata["repository_changes_allowed"] is False


def test_short_follow_up_uses_previous_objective():
    check, metadata = _conversation_gate(
        "build",
        "Build the previously discussed outcome: a restaurant website",
        {
            "original_follow_up": "Proceed",
            "previous_objective": "Build a restaurant website",
        },
    )

    assert check.status == "passed"
    assert metadata["execution_requested"] is True
    assert metadata["repository_changes_allowed"] is True
