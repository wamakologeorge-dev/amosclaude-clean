"""Contracts for the bounded Amosclaud daily proposal agent."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "amosclaud_cron_agent.py"
WORKFLOW = ROOT / ".github" / "workflows" / "daily-build.yml"


def _source() -> str:
    return AGENT.read_text(encoding="utf-8")


def _load_agent():
    spec = importlib.util.spec_from_file_location("amosclaud_cron_agent", AGENT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cron_agent_is_valid_python_and_uses_amosclaud_gateway() -> None:
    source = _source()

    ast.parse(source)
    assert "/v1/chat/completions" in source
    assert "AMOSCLAUD_API_KEY" in source
    assert "https://anthropic.com" not in source
    assert "ANTHROPIC_API_KEY" not in source


def test_cron_agent_never_force_pushes_or_writes_default_branch() -> None:
    source = _source()

    assert "--force" not in source
    assert 'branch = f"amosclaud-cron/{stamp}"' in source
    assert '["git", "push", "--set-upstream", "origin", branch]' in source
    assert '"base": DEFAULT_BRANCH' in source


def test_cron_agent_requires_runtime_changes_tests_and_verification() -> None:
    source = _source()

    assert "Generated patch does not modify an existing runtime component" in source
    assert "Generated patch must include test coverage" in source
    assert '"compileall"' in source
    assert '"pytest"' in source
    assert '["git", "diff", "--check"]' in source


def test_patch_validation_rejects_protected_paths() -> None:
    agent = _load_agent()
    patch = """diff --git a/.github/workflows/unsafe.yml b/.github/workflows/unsafe.yml
new file mode 100644
--- /dev/null
+++ b/.github/workflows/unsafe.yml
@@ -0,0 +1 @@
+name: unsafe
"""

    with pytest.raises(agent.CronAgentError, match="protected path"):
        agent.validate_patch(patch)


def test_patch_validation_accepts_bounded_runtime_and_test_change() -> None:
    agent = _load_agent()
    patch = """diff --git a/src/example.py b/src/example.py
--- a/src/example.py
+++ b/src/example.py
@@ -1 +1 @@
-old = True
+old = False
diff --git a/tests/test_example.py b/tests/test_example.py
--- a/tests/test_example.py
+++ b/tests/test_example.py
@@ -1 +1 @@
-assert True
+assert not False
"""

    assert agent.validate_patch(patch) == [
        "src/example.py",
        "tests/test_example.py",
    ]


def test_patch_validation_normalizes_dot_slash_paths_for_runtime_check() -> None:
    agent = _load_agent()
    patch = """diff --git a/./src/example.py b/./src/example.py
--- a/./src/example.py
+++ b/./src/example.py
@@ -1 +1 @@
-old = True
+old = False
diff --git a/tests/test_example.py b/tests/test_example.py
--- a/tests/test_example.py
+++ b/tests/test_example.py
@@ -1 +1 @@
-assert True
+assert not False
"""

    result = agent.validate_patch(patch)
    assert "src/example.py" in result
    assert "tests/test_example.py" in result


def test_daily_workflow_has_narrow_write_permissions_and_pinned_actions() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "contents: write" in workflow
    assert "pull-requests: write" in workflow
    assert "issues: write" in workflow
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in workflow
    assert "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97" in workflow
    assert "python amosclaud_cron_agent.py" in workflow
