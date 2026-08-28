from amoscloud_ai.autonomous_server import _conversation_gate


def test_native_issue_fix_button_is_explicit_execution_authorization():
    objective = "Work on native Amosclaud issue #6: fix the agent"
    check, metadata = _conversation_gate(
        "fix",
        objective,
        {
            "source": "native-platform-issue",
            "explicit_action": True,
            "original_follow_up": (
                "Proceed with the requested repository changes, execute the work, and verify the result."
            ),
            "previous_objective": objective,
        },
    )

    assert check.status == "passed"
    assert metadata["execution_requested"] is True
    assert metadata["repository_changes_allowed"] is True
    assert metadata["clarification_required"] is False
