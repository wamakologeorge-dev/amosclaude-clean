from amoscloud_ai.api.routes.agent import _is_guidance_request, _resolve_follow_up


def test_execution_follow_up_uses_previous_guidance_objective():
    objective, continued = _resolve_follow_up(
        "Now start to build",
        {"previous_objective": "Guide me on how to build a platform"},
    )

    assert continued is True
    assert objective == "Build the previously discussed outcome: Guide me on how to build a platform"


def test_verify_server_health_is_execution_not_generic_guidance():
    assert _is_guidance_request("verify server health", "autonomous-check") is False


def test_guidance_question_stays_conversational():
    assert _is_guidance_request("Guide me on how to build a platform", "autonomous-check") is True


def test_execution_follow_up_without_context_stays_explicit():
    objective, continued = _resolve_follow_up("Now start to build", {})

    assert continued is False
    assert objective == "Now start to build"
