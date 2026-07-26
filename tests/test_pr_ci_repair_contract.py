from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "amosclaud-repair-control-plane.yml"
SHIM = ROOT / ".github" / "workflows" / "amosclaud-pr-ci-repair.yml"
CANDIDATE = ROOT / ".github" / "scripts" / "amosclaud_repair_candidate.py"
POLICY = ROOT / ".amosclaud" / "repair-control-plane.json"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_pr_repair_is_routed_once_from_github_actions_and_circleci() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    shim = SHIM.read_text(encoding="utf-8")
    assert "workflow_run:" in source
    assert "status:" in source
    assert "contains(github.event.context, 'circleci')" in source
    assert "Route and deduplicate repair incident" in source
    assert "Remote pull request branch moved; refusing a stale push." in source
    assert "workflow_run:" not in shim
    assert "status:" not in shim


def test_model_verification_and_publish_credentials_are_step_isolated() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    reproduce = source.split("- name: Reproduce failure without repair credentials", 1)[1].split(
        "- name: Open scheduled incident", 1
    )[0]
    candidate = source.split("- name: Generate bounded repair candidate", 1)[1].split(
        "- name: Verify candidate in a credential-free adaptive pre-run", 1
    )[0]
    verify = source.split("- name: Verify candidate in a credential-free adaptive pre-run", 1)[1].split(
        "- name: Upload repair evidence", 1
    )[0]
    publish = source.split("- name: Publish verified repair safely", 1)[1].split(
        "- name: Mark incident as published", 1
    )[0]
    assert "AMOSCLAUD_API_KEY" not in reproduce
    assert "AMOSCLAUD_AUTONOMOUS_TOKEN" not in reproduce
    assert "AMOSCLAUD_API_KEY" in candidate
    assert "AMOSCLAUD_API_KEY" not in verify
    assert "AMOSCLAUD_AUTONOMOUS_TOKEN" not in verify
    assert "AMOSCLAUD_AUTONOMOUS_TOKEN" in publish
    assert source.count("persist-credentials: false") >= 2


def test_verified_pr_repair_returns_without_force_push() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert 'git -C target push origin "HEAD:refs/heads/${HEAD_REF}"' in source
    assert "--force" not in source
    assert "fix: Amosclaud repair [incident:${FINGERPRINT}]" in source
    assert "No force push was attempted" in source


def test_regular_and_maintenance_patch_boundaries() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    module = _load(CANDIDATE, "amosclaud_repair_candidate_contract")
    regular_protected = """diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -1 +1 @@
-old
+new
"""
    maintenance_without_test = """diff --git a/.github/workflows/amosclaud-fixer.yml b/.github/workflows/amosclaud-fixer.yml
--- a/.github/workflows/amosclaud-fixer.yml
+++ b/.github/workflows/amosclaud-fixer.yml
@@ -1 +1 @@
-old
+new
"""
    for patch, mode, expected in (
        (regular_protected, "regular", "protected path"),
        (maintenance_without_test, "maintenance", "regression test"),
    ):
        try:
            module.validate_patch(patch, policy, mode)
        except ValueError as error:
            assert expected in str(error)
        else:
            raise AssertionError(expected)


def test_workflow_actions_are_immutable_pins() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    refs = re.findall(r"^\s*uses:\s+([^\s#]+)", source, re.MULTILINE)
    assert refs
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref) for ref in refs)
