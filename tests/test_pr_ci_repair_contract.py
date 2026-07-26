from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "amosclaud-pr-ci-repair.yml"
PATCHER = ROOT / ".github" / "scripts" / "amosclaud_pr_ci_patch.py"
POLICY = ROOT / ".amosclaud" / "pr-ci-repair.json"


def _load_patcher():
    spec = importlib.util.spec_from_file_location("amosclaud_pr_ci_patch_contract", PATCHER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pr_repair_watches_github_actions_and_circleci_failures() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_run:" in source
    assert "status:" in source
    assert "startsWith(github.event.context, 'ci/circleci')" in source
    assert "github.event.workflow_run.conclusion == 'failure'" in source
    assert "github.event.workflow_run.head_repository.full_name == github.repository" in source
    assert "fork pull requests are never executed with repair credentials" in source


def test_pr_repair_uses_trusted_engine_and_exact_failed_revision() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    trusted = source.index("Check out trusted Amosclaud repair engine")
    target = source.index("Check out exact failed pull request revision")
    assert trusted < target
    assert "ref: ${{ github.event.repository.default_branch }}" in source
    assert "ref: ${{ steps.target.outputs.head_sha }}" in source
    assert source.count("persist-credentials: false") >= 2
    assert "pull request moved after the failed run; stale evidence was discarded" in source


def test_model_and_publish_credentials_are_separated_from_target_execution() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    reproduce = source.split("- name: Reproduce failure without repair credentials", 1)[1].split(
        "- name: Generate bounded repair candidate", 1
    )[0]
    verify = source.split("- name: Verify candidate in a fresh credential-free pre-run", 1)[1].split(
        "- name: Redact and upload repair evidence", 1
    )[0]
    candidate = source.split("- name: Generate bounded repair candidate", 1)[1].split(
        "- name: Verify candidate in a fresh credential-free pre-run", 1
    )[0]
    publish = source.split("- name: Publish verified repair to original pull request branch", 1)[1]

    assert "AMOSCLAUD_API_KEY" not in reproduce
    assert "AMOSCLAUD_AUTONOMOUS_TOKEN" not in reproduce
    assert "AMOSCLAUD_API_KEY" not in verify
    assert "AMOSCLAUD_AUTONOMOUS_TOKEN" not in verify
    assert "AMOSCLAUD_API_KEY" in candidate
    assert "AMOSCLAUD_AUTONOMOUS_TOKEN" in publish
    assert "credential-free pre-run" in source


def test_verified_repair_returns_to_original_pr_without_force_push() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert 'git -C target push origin "HEAD:refs/heads/${HEAD_REF}"' in source
    assert "--force" not in source
    assert "Remote pull request branch moved; refusing a stale push." in source
    assert 'fix: Amosclaud CI repair for PR #${PR_NUMBER}' in source
    assert "GitHub and external checks are running again" in source
    assert "steps.publish.outcome != 'success'" in source
    assert "No force push was attempted" in source


def test_repair_attempts_and_patch_scope_are_bounded_by_policy() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))

    assert policy["enabled"] is True
    assert policy["same_repository_pull_requests_only"] is True
    assert policy["max_repair_commits_per_pull_request"] == 3
    assert policy["max_changed_files"] <= 12
    assert policy["publishing"]["direct_default_branch_writes"] is False
    assert policy["publishing"]["force_push"] is False
    assert ".github/workflows/" in policy["protected_prefixes"]
    assert ".amosclaud/" in policy["protected_prefixes"]


def test_patcher_rejects_protected_paths_and_external_dependency_sources() -> None:
    patcher = _load_patcher()
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    protected = """diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -1 +1 @@
-old
+new
"""
    dependency = """diff --git a/requirements.txt b/requirements.txt
--- a/requirements.txt
+++ b/requirements.txt
@@ -1 +1,2 @@
 pytest
+unsafe @ https://example.invalid/package.whl
"""

    for patch, expected in (
        (protected, "protected path"),
        (dependency, "external dependency source"),
    ):
        try:
            patcher._validate_patch(patch, policy)
        except ValueError as error:
            assert expected in str(error)
        else:
            raise AssertionError(f"patch should be rejected: {expected}")


def test_patcher_only_applies_candidate_and_never_executes_target_tests() -> None:
    source = PATCHER.read_text(encoding="utf-8")

    assert "Verification happens later in a separate workflow step" in source
    assert '"verification_required": True' in source
    assert '"git",\n            "apply"' in source
    assert "pip install" not in source
    assert "python -m pytest" not in source
    assert "compileall" not in source


def test_workflow_actions_are_immutable_pins() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    refs = re.findall(r"^\s*uses:\s+([^\s#]+)", source, re.MULTILINE)

    assert refs
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref) for ref in refs)
