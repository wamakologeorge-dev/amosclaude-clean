from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_WORKFLOW = ROOT / ".github" / "workflows" / "amosclaud-issue-build.yml"
CHAT_WORKFLOW = ROOT / ".github" / "workflows" / "amosclaud-github-chat.yml"
BUILDER = ROOT / ".github" / "scripts" / "amosclaud_build_candidate.py"


def test_issue_build_has_write_permissions_and_pr_publication() -> None:
    source = BUILD_WORKFLOW.read_text(encoding="utf-8")
    assert "contents: write" in source
    assert "issues: write" in source
    assert "pull-requests: write" in source
    assert "gh pr create" in source
    assert 'git -C target push origin "HEAD:refs/heads/${branch}"' in source
    assert "No direct write to the default branch was made." in source


def test_issue_build_is_trusted_user_only_and_never_shell_interpolates_comment() -> None:
    source = BUILD_WORKFLOW.read_text(encoding="utf-8")
    assert "{'OWNER', 'MEMBER', 'COLLABORATOR'}" in source
    assert "${{ github.event.comment.body }}" not in source
    assert "GITHUB_EVENT_PATH" in source
    assert "github.event.issue.pull_request == null" in source


def test_issue_build_reuses_credential_free_verification() -> None:
    source = BUILD_WORKFLOW.read_text(encoding="utf-8")
    assert "amosclaud_build_candidate.py" in source
    assert "amosclaud_repair_verify.py" in source
    assert "Verify candidate without credentials" in source


def test_issue_build_pins_exact_default_branch_revision() -> None:
    source = BUILD_WORKFLOW.read_text(encoding="utf-8")
    assert "base_sha = subprocess.check_output" in source
    assert "ref: ${{ steps.request.outputs.base_sha }}" in source
    assert "git -C target rev-parse HEAD" in source
    assert '!= "$BUILD_BASE_SHA"' in source


def test_chat_routes_issue_build_and_fix_away_from_read_only_model() -> None:
    source = CHAT_WORKFLOW.read_text(encoding="utf-8")
    assert "github.event.issue.pull_request == null" in source
    assert "/amosclaud build" in source
    assert "@amosclaud build" in source
    assert "/amosclaud fix" in source
    assert "@amosclaud fix" in source


def test_builder_implements_instead_of_only_planning() -> None:
    source = BUILDER.read_text(encoding="utf-8")
    assert "Implement the user's requested product" in source
    assert "create a coherent minimal runnable foundation" in source
    assert "never attempt to push, merge, force-push" in source


def test_builder_keeps_guarded_validation_and_scaffold_budget() -> None:
    source = BUILDER.read_text(encoding="utf-8")
    assert "guarded.validate_patch" in source
    assert 'regular["max_changed_files"]' in source
    assert "30" in source
    assert 'regular["max_patch_bytes"]' in source
    assert "750000" in source
