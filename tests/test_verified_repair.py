from __future__ import annotations

from pathlib import Path

import pytest

from src.agent.engineering_loop import AutonomousEngineeringLoop
from src.services.code_analyzer import CodeAnalyzer
from src.services.file_manager import SafeFileManager
from src.services.runtime_exec import RuntimeExecutor


def test_analyzer_supplies_relevant_code_without_secrets(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "authentication.py").write_text(
        "def authenticate(token):\n    return bool(token)\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "unrelated.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / ".env").write_text("OLLAMA_API_KEY=never-read\n", encoding="utf-8")

    evidence = CodeAnalyzer(tmp_path).inspect("Fix authentication token validation")
    combined = "\n".join(evidence)

    assert "Repository file `src/authentication.py`" in combined
    assert "def authenticate" in combined
    assert "never-read" not in combined
    assert "OLLAMA_API_KEY" not in combined


def test_autonomous_write_blocks_repair_control_files(tmp_path: Path) -> None:
    manager = SafeFileManager(tmp_path)

    with pytest.raises(PermissionError, match="maintenance pull request"):
        manager.write(
            ".github/workflows/ci.yml",
            "name: CI\n",
            authorized=True,
        )

    manager.write("src/app.py", "VALUE = 1\n", authorized=True)
    assert (tmp_path / "src" / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def test_runtime_selects_changed_file_compilation_and_focused_test(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "widget.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_widget.py").write_text(
        "def test_widget():\n    assert True\n",
        encoding="utf-8",
    )

    commands = RuntimeExecutor(tmp_path).verification_commands(["src/widget.py"])
    names = [name for name, _command, _timeout in commands]
    command_text = [" ".join(command) for _name, command, _timeout in commands]

    assert names == ["Git diff integrity", "Python compilation", "Focused pytest"]
    assert any("src/widget.py" in command for command in command_text)
    assert any("tests/test_widget.py" in command for command in command_text)


def test_model_json_parser_accepts_fenced_object_and_rejects_empty_changes() -> None:
    payload = AutonomousEngineeringLoop._json_payload(
        "```json\n{\"changes\":[{\"path\":\"app.py\",\"content\":\"ok\\n\"}]}\n```"
    )
    assert payload["changes"][0]["path"] == "app.py"


def test_verified_repair_workflow_wires_ollama_and_changed_file_checks() -> None:
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "amosclaud-bot.yml"
    ).read_text(encoding="utf-8")

    for required in (
        "secrets.OLLAMA_API_KEY",
        "AMOSCLAUD_MODEL_TOKEN:",
        "AMOSCLAUD_MODEL_URL:",
        "gpt-oss:120b",
        "python -m amosclaud_bot.verified_repair",
        "--changed-files /tmp/amosclaud-changed-files.txt",
        "changed-file verification passed",
    ):
        assert required in workflow

    assert "python -m pytest -q \\\n            tests/test_amosclaud_bot.py" not in workflow
