from amosclaud_bot.privacy_gate import requires_private_work


def test_serious_write_work_is_private_by_default() -> None:
    assert requires_private_work("fix production deployment workflow", command="fix")
    assert requires_private_work("investigate security vulnerability", command="fix")
    assert requires_private_work("rotate authentication credential", command="fix")
    assert requires_private_work("handle confidential customer data incident", command="fix")


def test_safe_process_work_can_remain_public() -> None:
    assert not requires_private_work("fix typo in README", command="fix")
    assert not requires_private_work("add unit test for parser", command="fix")
    assert not requires_private_work("inspect code quality", command="inspect")


def test_read_only_deployment_inspection_is_not_misclassified_private() -> None:
    objective = (
        "Inspect this repository and identify the main application entry point, "
        "test framework, Docker configuration, and deployment workflow. "
        "Do not modify files. Return exact file paths and evidence."
    )
    assert not requires_private_work(objective, command="inspect")


def test_explicit_disclosure_risk_remains_private_in_read_only_mode() -> None:
    assert requires_private_work(
        "inspect a security vulnerability and confidential incident notes",
        command="inspect",
    )
    assert requires_private_work("review credential handling details", command="review")


def test_hint_matching_does_not_trigger_on_substrings() -> None:
    assert not requires_private_work("inspect the tokenizer implementation", command="inspect")
    assert not requires_private_work("fix tokenizer spacing", command="fix")
