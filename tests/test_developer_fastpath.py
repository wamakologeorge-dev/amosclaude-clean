from pathlib import Path

from amoscloud_ai.developer_fastpath import compress_context, quickcheck, validate_repository
from amoscloud_ai.quickcheck_cli import main


def test_context_compression_excludes_dependencies_and_sensitive_files(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text(
        "def verify_login(token):\n"
        "    if not token:\n"
        "        raise ValueError('missing token')\n"
        "    return True\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "Authentication uses verify_login.\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("SECRET=do-not-read\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "auth.js").write_text(
        "const secret = 'ignore';\n",
        encoding="utf-8",
    )

    result = compress_context(
        tmp_path,
        "Fix the login token verification",
        max_lines=50,
        max_files=4,
    )

    assert result["selected_lines"] <= 50
    assert any(item["path"] == "src/auth.py" for item in result["snippets"])
    assert ".env" in result["sensitive_files_skipped"]
    assert all("node_modules" not in item["path"] for item in result["snippets"])
    rendered = "\n".join(line["text"] for item in result["snippets"] for line in item["lines"])
    assert "do-not-read" not in rendered


def test_guardrails_find_invalid_python_json_and_merge_markers(tmp_path: Path) -> None:
    (tmp_path / "broken.py").write_text("def broken(:\n    pass\n", encoding="utf-8")
    (tmp_path / "config.json").write_text('{"enabled": true,,}\n', encoding="utf-8")
    (tmp_path / "notes.md").write_text(
        "<<<<<<< HEAD\nconflict\n=======\n",
        encoding="utf-8",
    )

    result = validate_repository(tmp_path)
    failure_checks = {(item["path"], item["check"]) for item in result["failures"]}

    assert result["passed"] is False
    assert ("broken.py", "python-ast") in failure_checks
    assert ("config.json", "json") in failure_checks
    assert ("notes.md", "merge-markers") in failure_checks


def test_quickcheck_cli_returns_machine_readable_result(
    tmp_path: Path,
    capsys,
) -> None:
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")

    exit_code = main(
        [
            str(tmp_path),
            "--objective",
            "Find the application value",
            "--json",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert '"status": "passed"' in output
    assert '"selected_lines":' in output


def test_quickcheck_combines_context_and_guardrails(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text("def health():\n    return True\n", encoding="utf-8")

    result = quickcheck(tmp_path, "Check service health")

    assert result["status"] == "passed"
    assert result["context"]["selected_files"] == 1
    assert result["guardrails"]["passed"] is True


def test_pyproject_publishes_zero_config_quick_command() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'amosclaud-quick = "amoscloud_ai.quickcheck_cli:main"' in pyproject
