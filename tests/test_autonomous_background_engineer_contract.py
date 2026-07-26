from __future__ import annotations

import importlib.util
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
REDACTOR = ROOT / ".github" / "scripts" / "redact_amosclaud_evidence.py"
REQUIREMENTS = ROOT / "requirements.txt"


def _load_fixer():
    spec = importlib.util.spec_from_file_location("amosclaud_fixer_contract", FIXER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_verified_repairs_use_check_triggering_token_and_auto_merge() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "AMOSCLAUD_AUTONOMOUS_TOKEN" in workflow
    assert "persist-credentials: false" in workflow
    assert "GH_TOKEN: ${{ secrets.AMOSCLAUD_AUTONOMOUS_TOKEN }}" in workflow
    assert 'gh pr merge "$pr_url" --auto --squash --delete-branch' in workflow
    assert "Human approval: not required" in workflow
    assert "Direct default-branch writes: prohibited" in workflow
    assert "<!-- amosclaud-autonomous-repair:v1 -->" in workflow
    assert "Human review is still required" not in workflow
    assert "needs owner review" not in workflow


def test_daily_inspection_opens_issue_before_the_fixer_and_pull_request() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "cron: '17 4 * * *'" in workflow
    assert "Inspect repository health before opening an issue" in workflow
    issue_step = workflow.index(
        "Create or update repair issue before Amosclaud Fixer runs"
    )
    fixer_step = workflow.index("Run Amosclaud autonomous background engineer")
    publish_step = workflow.index("Publish verified repair and enable autonomous merge")
    assert issue_step < fixer_step < publish_step
    assert "Daily Amosclaud inspection passed. No issue" in workflow
    assert "Repair issue: #${ISSUE_NUMBER}" in workflow


def test_dependency_install_failure_is_handed_to_autonomous_repair() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    bot = BOT.read_text(encoding="utf-8")
    fixer = FIXER.read_text(encoding="utf-8")

    assert "Install repository dependencies or capture the blocker" in workflow
    assert "> amosclaud-failure.log" in workflow
    assert "Fail closed when repair engine is unavailable" in workflow
    assert "PREVIOUS WORKFLOW FAILURE EVIDENCE" in bot
    assert "SECTION_LIMIT" in bot
    assert '"pip",\n            "install"' in fixer
    assert '"-e",\n            "."' in fixer


def test_fixer_follows_and_protects_repository_instructions() -> None:
    fixer = _load_fixer()
    source = FIXER.read_text(encoding="utf-8")
    instruction_patch = """diff --git a/AGENTS.md b/AGENTS.md
--- a/AGENTS.md
+++ b/AGENTS.md
@@ -1 +1 @@
-old
+new
"""

    assert "AGENTS.md" in fixer.repository_instructions()
    assert "PYTHON AUTONOMOUS ENGINEERING BOOK" in fixer.repository_instructions()
    assert "Follow AGENTS.md" in source
    assert "Do not perform feature work" in source
    try:
        fixer.validate_patch(instruction_patch)
    except ValueError as error:
        assert "protected path" in str(error)
    else:
        raise AssertionError("repository instructions must be immutable to the fixer")


def test_fixer_validates_deleted_and_self_protected_paths() -> None:
    fixer = _load_fixer()
    deletion = """diff --git a/.github/actions/unsafe/action.yml b/.github/actions/unsafe/action.yml
--- a/.github/actions/unsafe/action.yml
+++ /dev/null
@@ -1 +0,0 @@
-name: unsafe
"""

    assert ".github/actions/unsafe/action.yml" in fixer.patch_paths(deletion)
    try:
        fixer.validate_patch(deletion)
    except ValueError as error:
        assert "protected path" in str(error)
    else:
        raise AssertionError("protected deletion must be rejected")

    source = FIXER.read_text(encoding="utf-8")
    assert '".github/scripts/"' in source
    assert '".github/amosclaud-fixer/"' in source


def test_each_candidate_is_verified_in_a_fresh_environment() -> None:
    source = FIXER.read_text(encoding="utf-8")

    assert "TemporaryDirectory" in source
    assert '"-m", "venv"' in source
    assert "verify(attempt)" in source


def test_evidence_is_redacted_before_upload_and_raw_patches_are_not_uploaded() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    redactor = REDACTOR.read_text(encoding="utf-8")

    assert "Redact engineering evidence" in workflow
    assert "redact_amosclaud_evidence.py" in workflow
    assert "amosclaud-fix-attempt-*.patch" not in workflow
    assert "[REDACTED]" in redactor
    assert "artifact evidence truncated" in redactor


def test_retry_incidents_are_revision_scoped_and_close_only_after_merge() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    fixer = FIXER.read_text(encoding="utf-8")

    assert 'title="Amosclaud autonomous repair ${short_sha}"' in workflow
    assert "close-merged-repair-incident" in workflow
    assert "github.event.pull_request.merged == true" in workflow
    assert "remains open until GitHub confirms" in workflow
    assert "No human approval is requested" in workflow
    assert '"next_action": "scheduled autonomous retry"' in fixer


def test_linter_dependency_constraints_can_be_resolved_together() -> None:
    requirements = REQUIREMENTS.read_text(encoding="utf-8")

    assert "pylint>=4.0.6,<5" in requirements
    assert "isort>=8.0.1,<9" in requirements
    assert "pylint>=3,<4" not in requirements
