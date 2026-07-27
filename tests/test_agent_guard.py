from __future__ import annotations

from pathlib import Path

import pytest

from amoscloud_ai.local_cloud.agent_guard import (
    AgentBuildGuard,
    AgentGuardError,
    BuildFailureContext,
    CommandResult,
)


class FixModel:
    def propose_patch(self, context: BuildFailureContext) -> str:
        assert "app.py" in context.output
        return """--- a/app.py
+++ b/app.py
@@ -1,1 +1,1 @@
-broken = True
+broken = False
"""


class UnsafeModel:
    def propose_patch(self, context: BuildFailureContext) -> str:
        return """--- a/.env
+++ b/.env
@@ -1,1 +1,1 @@
-SECRET=old
+SECRET=new
"""


def test_guard_applies_patch_and_verifies(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text("broken = True\n", encoding="utf-8")

    def runner(command, cwd, env, timeout):
        if "True" in source.read_text(encoding="utf-8"):
            return CommandResult(1, "", 'File "app.py", line 1\nAssertionError')
        return CommandResult(0, "passed", "")

    result = AgentBuildGuard(tmp_path, FixModel(), runner=runner).run(
        ["python", "-m", "pytest"],
        label="python verification",
        timeout=60,
    )
    assert result.status == "succeeded"
    assert result.changed_files == ("app.py",)
    assert source.read_text(encoding="utf-8") == "broken = False\n"


def test_guard_rolls_back_after_final_failure(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text("broken = True\n", encoding="utf-8")

    def runner(command, cwd, env, timeout):
        return CommandResult(1, "", 'File "app.py", line 1\nStill broken')

    result = AgentBuildGuard(
        tmp_path, FixModel(), maximum_attempts=2, runner=runner
    ).run(
        ["python", "-m", "pytest"],
        label="python verification",
        timeout=60,
    )
    assert result.status == "failed"
    assert result.rolled_back is True
    assert source.read_text(encoding="utf-8") == "broken = True\n"


def test_guard_rejects_protected_paths(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET=old\n", encoding="utf-8")

    def runner(command, cwd, env, timeout):
        return CommandResult(1, "", "configuration failed")

    guard = AgentBuildGuard(tmp_path, UnsafeModel(), runner=runner)
    with pytest.raises(AgentGuardError, match="protected"):
        guard.run(["python", "-m", "pytest"], label="test", timeout=60)
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "SECRET=old\n"


def test_guard_rejects_symlink_targets(tmp_path: Path) -> None:
    target = tmp_path / "real.py"
    target.write_text("broken = True\n", encoding="utf-8")
    link = tmp_path / "app.py"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable on this platform")

    def runner(command, cwd, env, timeout):
        return CommandResult(1, "", 'File "app.py", line 1\nAssertionError')

    guard = AgentBuildGuard(tmp_path, FixModel(), runner=runner)
    with pytest.raises(AgentGuardError, match="symlink"):
        guard.run(["python", "-m", "pytest"], label="test", timeout=60)
    assert target.read_text(encoding="utf-8") == "broken = True\n"
