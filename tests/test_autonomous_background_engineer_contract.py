from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "amosclaud-autonomous-background-engineer.yml"
BOT = (
    ROOT
    / ".github"
    / "amosclaud-fixer"
    / "amosclaud-autonomous-agent"
    / "ci"
    / "bot-fixer-operations-autonomous-background-engineer"
    / "bot.py"
)
FIXER = ROOT / ".github" / "scripts" / "amosclaud_fixer.py"
REQUIREMENTS = ROOT / "requirements.txt"


def test_verified_repairs_enable_auto_merge_without_human_approval() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "gh pr merge \"$pr_url\" --auto --squash --delete-branch" in workflow
    assert "Human approval: not required" in workflow
    assert "Human review is still required" not in workflow
    assert "needs owner review" not in workflow


def test_dependency_install_failure_is_handed_to_autonomous_repair() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    bot = BOT.read_text(encoding="utf-8")
    fixer = FIXER.read_text(encoding="utf-8")

    assert "Install repository dependencies or capture the blocker" in workflow
    assert "> amosclaud-failure.log" in workflow
    assert "PREVIOUS WORKFLOW FAILURE EVIDENCE" in bot
    assert '"pip",\n        "install"' in fixer
    assert '"-e",\n        "."' in fixer


def test_linter_dependency_constraints_can_be_resolved_together() -> None:
    requirements = REQUIREMENTS.read_text(encoding="utf-8")

    assert "pylint>=4.0.6,<5" in requirements
    assert "isort>=8.0.1,<9" in requirements
    assert "pylint>=3,<4" not in requirements


def test_failed_attempts_queue_an_autonomous_retry_instead_of_owner_review() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    fixer = FIXER.read_text(encoding="utf-8")

    assert "Amosclaud autonomous repair retry queued" in workflow
    assert "No human approval is requested" in workflow
    assert '"next_action": "scheduled autonomous retry"' in fixer
