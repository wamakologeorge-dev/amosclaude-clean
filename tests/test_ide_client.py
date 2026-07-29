from pathlib import Path

import pytest

from amoscloud_ai.ide_client import (
    MAX_SELECTION_CHARS,
    IDEClientError,
    bounded_selection,
    build_context,
    build_payload,
    is_sensitive_path,
    normalize_base_url,
    read_selection_file,
    validate_relative_path,
)


def test_normalize_base_url_requires_https_except_exact_loopback():
    assert normalize_base_url("https://www.amosclaud.com/") == "https://www.amosclaud.com"
    assert normalize_base_url("http://localhost:8000/") == "http://localhost:8000"
    assert normalize_base_url("http://127.0.0.1:8000/") == "http://127.0.0.1:8000"
    with pytest.raises(IDEClientError):
        normalize_base_url("http://example.com")
    with pytest.raises(IDEClientError):
        normalize_base_url("http://localhost.example.com")


def test_relative_editor_paths_reject_escape_and_absolute_paths():
    assert validate_relative_path("src/main.py") == "src/main.py"
    with pytest.raises(IDEClientError):
        validate_relative_path("../secrets.txt")
    with pytest.raises(IDEClientError):
        validate_relative_path("/tmp/file.py")


def test_sensitive_paths_are_blocked_from_editor_context():
    assert is_sensitive_path(".env")
    assert is_sensitive_path("config/.env.production")
    assert is_sensitive_path("certs/server.pem")
    assert is_sensitive_path("secrets/provider.json")
    with pytest.raises(IDEClientError):
        build_context(file_path="config/.env.production", selection="SECRET=value")


def test_selection_is_bounded_before_it_enters_pipeline_metadata():
    value = "x" * (MAX_SELECTION_CHARS + 500)
    assert len(bounded_selection(value)) == MAX_SELECTION_CHARS
    context = build_context(file_path="src/app.py", selection=value)
    assert len(context["selection"]) == MAX_SELECTION_CHARS


def test_selection_file_reads_only_the_bounded_context(tmp_path: Path):
    selection = tmp_path / "selection.txt"
    selection.write_text("y" * (MAX_SELECTION_CHARS + 200), encoding="utf-8")
    assert len(read_selection_file(str(selection))) == MAX_SELECTION_CHARS


def test_selection_file_rejects_a_sensitive_parent_directory(tmp_path: Path):
    secret_directory = tmp_path / "secrets"
    secret_directory.mkdir()
    selection = secret_directory / "selection.txt"
    selection.write_text("provider-token", encoding="utf-8")
    with pytest.raises(IDEClientError):
        read_selection_file(str(selection))


def test_payload_preserves_one_autonomous_request_and_optional_capability():
    context = build_context(
        repository="wamakologeorge-dev/amosclaude-clean",
        branch="feature/test",
        file_path="tests/test_api.py",
        language="python",
        selection="def test_example(): pass",
        source="unit-test",
    )
    payload = build_payload("Fix this test", requested_agent="fixer", context=context)
    assert payload == {
        "task": "Fix this test",
        "requested_agent": "fixer",
        "context": context,
    }


def test_empty_task_is_rejected():
    with pytest.raises(IDEClientError):
        build_payload("   ")
