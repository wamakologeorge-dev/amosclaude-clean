import json
from pathlib import Path

from amoscloud_ai.isolated_runner import (
    IsolatedRunResult,
    RunnerConfigurationError,
    parse_allowed_command,
)
from src.services.runtime_exec import RuntimeExecutor


def test_runtime_selects_changed_file_compilation_and_focused_test(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "widget.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_widget.py").write_text(
        "def test_widget():\n    assert True\n", encoding="utf-8"
    )

    commands = RuntimeExecutor(tmp_path).verification_commands(["src/widget.py"])
    names = [name for name, _command, _timeout in commands]
    command_text = [" ".join(command) for _name, command, _timeout in commands]

    assert names == ["Python compilation", "Focused pytest"]
    assert any("src/widget.py" in command for command in command_text)
    assert any("tests/test_widget.py" in command for command in command_text)


def test_runtime_keeps_git_integrity_in_the_verification_plan(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    commands = RuntimeExecutor(tmp_path).verification_commands([])
    assert commands[0] == (
        "Git diff integrity",
        ["git", "diff", "--check"],
        60,
    )


def test_runtime_wraps_git_execution_inside_the_container(tmp_path: Path) -> None:
    calls = []

    def fake_runner(command, **kwargs):
        calls.append(command)
        return IsolatedRunResult(0, "clean")

    result = RuntimeExecutor(tmp_path, runner=fake_runner)._run(
        ["git", "diff", "--check"], name="Git diff integrity"
    )

    assert result["passed"] is True
    assert result["command"] == "git diff --check"
    assert calls and calls[0].startswith("python -c ")
    assert "git" in calls[0] and "diff" in calls[0]


def test_runtime_keeps_metacharacters_inside_one_argument(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    suspicious = "src/widget;touch-owned.py"
    (tmp_path / suspicious).write_text("VALUE = 1\n", encoding="utf-8")
    calls = []

    def fake_runner(command, **kwargs):
        calls.append(parse_allowed_command(command, {"python"}))
        return IsolatedRunResult(0, "compiled")

    results = RuntimeExecutor(tmp_path, runner=fake_runner).verify([suspicious])

    assert results[0]["passed"] is True
    assert calls == [["python", "-m", "py_compile", suspicious]]


def test_runtime_selects_frontend_typecheck_tests_and_build(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.ts").write_text(
        "export const value = 1;\n", encoding="utf-8"
    )
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "scripts": {
                    "typecheck": "tsc --noEmit",
                    "test": "vitest run",
                    "build": "vite build",
                }
            }
        ),
        encoding="utf-8",
    )

    commands = RuntimeExecutor(tmp_path).verification_commands(["src/app.ts"])
    names = [name for name, _command, _timeout in commands]
    assert names == ["Frontend typecheck", "Frontend tests", "Frontend build"]


def test_runtime_executes_each_check_through_the_isolated_runner(tmp_path: Path) -> None:
    calls = []

    def fake_runner(command, **kwargs):
        calls.append((command, kwargs))
        return IsolatedRunResult(0, "compiled successfully")

    result = RuntimeExecutor(tmp_path, runner=fake_runner)._run(
        ["python", "-m", "py_compile", "app.py"],
        timeout=45,
        name="Python compilation",
    )

    assert result["passed"] is True
    assert result["isolated"] is True
    assert result["runtime"] == "docker"
    assert calls[0][0] == "python -m py_compile app.py"
    assert calls[0][1]["workspace"] == tmp_path.resolve()
    assert calls[0][1]["timeout_seconds"] == 45
    assert calls[0][1]["environment"]["CI"] == "1"


def test_runtime_fails_closed_when_container_runner_is_unavailable(tmp_path: Path) -> None:
    def blocked_runner(command, **kwargs):
        raise RunnerConfigurationError("Docker is required")

    result = RuntimeExecutor(tmp_path, runner=blocked_runner)._run(
        ["python", "--version"], name="Runner health"
    )

    assert result["passed"] is False
    assert result["exit_code"] == 126
    assert "Docker is required" in result["output"]
    assert result["isolated"] is True
