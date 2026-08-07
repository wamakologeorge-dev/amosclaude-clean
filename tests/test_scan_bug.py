from __future__ import annotations

import hashlib
from pathlib import Path

from amoscloud_ai.scan_bug import scan_repository


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_scan_bug_visits_every_eligible_line_without_mutating_files(tmp_path: Path) -> None:
    python_file = tmp_path / "app.py"
    json_file = tmp_path / "config.json"
    python_file.write_text("value = 1\nvalue += 1\nprint(value)\n", encoding="utf-8")
    json_file.write_text('{\n  "enabled": true\n}\n', encoding="utf-8")
    before = {path.name: _digest(path) for path in (python_file, json_file)}

    report = scan_repository(tmp_path, snapshot_path=tmp_path / "artifacts" / "catch.svg")

    assert report.status == "complete"
    assert report.files_scanned == 2
    assert report.lines_scanned == 6
    assert report.finding is None
    assert before == {path.name: _digest(path) for path in (python_file, json_file)}


def test_scan_bug_stops_at_first_catch_and_redacts_snapshot(tmp_path: Path) -> None:
    first = tmp_path / "a.py"
    second = tmp_path / "z.py"
    first.write_text('api_key = "super-secret-value"\nvalue = 1  \n', encoding="utf-8")
    second.write_text("this file must not be reached\n", encoding="utf-8")
    snapshot = tmp_path / "artifacts" / "catch.svg"

    report = scan_repository(tmp_path, snapshot_path=snapshot)

    assert report.status == "caught"
    assert report.finding is not None
    assert report.finding.code == "trailing-whitespace"
    assert report.finding.path == "a.py"
    assert report.finding.line == 2
    assert report.files_scanned == 1
    assert [item.path for item in report.coverage] == ["a.py"]
    rendered = snapshot.read_text(encoding="utf-8")
    assert "super-secret-value" not in rendered
    assert "[REDACTED]" in rendered


def test_scan_bug_catches_unconditional_test_skip(tmp_path: Path) -> None:
    test_file = tmp_path / "test_feature.py"
    test_file.write_text(
        "import pytest\n\n@pytest.mark.skip(reason='hidden failure')\ndef test_feature():\n    pass\n",
        encoding="utf-8",
    )

    report = scan_repository(tmp_path, snapshot_path=tmp_path / "skip.svg")

    assert report.status == "caught"
    assert report.finding is not None
    assert report.finding.code == "unconditional-test-skip"
    assert report.finding.path == "test_feature.py"
    assert report.finding.line == 3


def test_explicit_allow_skip_marker_is_auditable_escape_hatch(tmp_path: Path) -> None:
    test_file = tmp_path / "test_platform.py"
    test_file.write_text(
        "import pytest\n\n"
        "@pytest.mark.skip(reason='platform unavailable')  # amosclaud: allow-skip\n"
        "def test_platform():\n"
        "    pass\n",
        encoding="utf-8",
    )

    report = scan_repository(tmp_path, snapshot_path=tmp_path / "skip.svg")

    assert report.status == "complete"
    assert report.finding is None


def test_binary_files_are_recorded_but_do_not_create_fake_source_lines(tmp_path: Path) -> None:
    image = tmp_path / "logo.png"
    source = tmp_path / "main.py"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    source.write_text("answer = 42\n", encoding="utf-8")

    report = scan_repository(tmp_path, snapshot_path=tmp_path / "catch.svg")

    assert report.status == "complete"
    assert report.files_scanned == 1
    assert report.lines_scanned == 1
    assert [(item.path, item.reason) for item in report.exclusions] == [
        ("logo.png", "binary file; no source lines")
    ]


def test_syntax_failure_is_captured_after_all_lines_in_the_file_are_seen(tmp_path: Path) -> None:
    source = tmp_path / "broken.py"
    source.write_text("def broken():\n    value = (1 +\n    return value\n", encoding="utf-8")

    report = scan_repository(tmp_path, snapshot_path=tmp_path / "syntax.svg")

    assert report.status == "caught"
    assert report.finding is not None
    assert report.finding.code == "python-syntax"
    assert report.lines_scanned == 3
    assert report.coverage[0].lines_scanned == 3


def test_scan_bug_workflow_is_not_a_repository_test_gate() -> None:
    workflow = Path(".github/workflows/amosclaud-scan-bug.yml").read_text(encoding="utf-8")

    assert "continue-on-error: true" in workflow
    assert "Repository tests were not stopped by this workflow" in workflow
    assert "python -m amoscloud_ai.scan_bug" in workflow
    assert "gh workflow run amosclaud-repair-control-plane.yml" in workflow
    assert "needs:" not in workflow
