from amosclaud_bot.autonomous_planning import format_plan
from amosclaud_bot.codex_capabilities import prepare_codex_capabilities


def test_fix_uses_engineering_skill_and_bounded_tools() -> None:
    context = prepare_codex_capabilities("fix", "repair the failing Python tests")
    assert context["skill"]["name"] == "engineering"
    assert "repository.write" in context["write_tools"]
    assert "repository.write" in context["approval_tools"]
    assert context["verification"]["completion_requires_pass"] is True
    assert context["verification"]["rollback_on_failed_verification"] is True
    assert context["external_model_execution"] is False


def test_inspection_can_select_research_operations_without_write_authority() -> None:
    context = prepare_codex_capabilities("inspect", "investigate why the deployment health check failed")
    assert context["skill"]["name"] == "research-operations"
    assert context["skill"]["default_write_policy"] == "deny"
    assert "repository.write" not in context["write_tools"]


def test_codex_context_is_secret_free_and_workspace_confined() -> None:
    context = prepare_codex_capabilities("verify", "verify the current pull request")
    assert context["bundle"]["contains_secrets"] is False
    assert context["workspace"]["confined"] is True
    assert context["workspace"]["allow_parent_traversal"] is False
    assert context["workspace"]["allow_secret_files"] is False


def test_bot_plan_displays_codex_skill_limits_and_gates() -> None:
    context = prepare_codex_capabilities("fix", "repair a deterministic test failure")
    rendered = format_plan("fix", "repair a deterministic test failure", codex_context=context)
    assert "Autonomous Codex capability context" in rendered
    assert "Codex Engineering Skill" in rendered
    assert "Tools still requiring approval" in rendered
    assert "Required checks" in rendered
    assert "External model execution:** disabled" in rendered
    assert "privacy, approval, verification, rollback" in rendered
