from pathlib import Path


WORKFLOWS = Path(".github/workflows")


def test_legacy_external_issue_assistant_is_removed() -> None:
    assert not (WORKFLOWS / "issue-bot.yml").exists()
    assert not Path("scripts/issue_bot.py").exists()


def test_github_copilot_repository_hooks_are_removed() -> None:
    assert not Path(".github/copilot-instructions.md").exists()
    assert not (WORKFLOWS / "copilot-setup-steps.yml").exists()
    assert not (WORKFLOWS / "copilot-setup-steps.yaml").exists()


def test_workflows_do_not_require_github_copilot_credentials() -> None:
    forbidden = (
        "COPILOT_GITHUB_TOKEN",
        "copilot-setup-steps",
        "github/copilot",
        "gh copilot",
        "copilot-swe-agent",
    )
    for workflow in sorted((*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml"))):
        source = workflow.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in source, f"{workflow} reintroduced {marker}"


def test_canonical_amosclaud_workflow_remains_present() -> None:
    workflow = (WORKFLOWS / "amosclaud-bot.yml").read_text(encoding="utf-8")

    assert "name: Amosclaud Bot" in workflow
    assert "issue_comment:" in workflow
    assert "python -m amosclaud_bot.dispatcher" in workflow
    assert "GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in workflow
