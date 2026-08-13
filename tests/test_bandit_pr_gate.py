from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci.bandit_pr_gate import compare_reports, load_report, render_markdown


def report(path: Path, results: list[dict[str, object]]) -> Path:
    path.write_text(json.dumps({"results": results}), encoding="utf-8")
    return path


def finding(
    *,
    test_id: str = "B602",
    filename: str = "src/build.py",
    line_number: int = 10,
    source: str = "subprocess.run(command, shell=True)",
    severity: str = "HIGH",
) -> dict[str, object]:
    return {
        "test_id": test_id,
        "test_name": "example",
        "issue_severity": severity,
        "issue_confidence": "HIGH",
        "filename": filename,
        "line_number": line_number,
        "issue_text": "Example security finding",
        "code": f"{line_number - 1} before\n{line_number} {source}\n{line_number + 1} after",
        "more_info": "https://example.invalid/finding",
    }


def test_identical_base_finding_is_not_reclassified_as_new(tmp_path: Path) -> None:
    base = load_report(report(tmp_path / "base.json", [finding(line_number=10)]))
    head = load_report(report(tmp_path / "head.json", [finding(line_number=80)]))

    result = compare_reports(base, head)

    assert result.status == "PASSED"
    assert result.base_count == 1
    assert result.head_count == 1
    assert result.new_findings == ()


def test_every_new_finding_is_blocking_regardless_of_severity(tmp_path: Path) -> None:
    base = load_report(report(tmp_path / "base.json", []))
    head = load_report(
        report(
            tmp_path / "head.json",
            [
                finding(test_id="B105", severity="LOW", source='secret = "value"'),
                finding(test_id="B104", severity="MEDIUM", source='host = "0.0.0.0"'),
                finding(test_id="B602", severity="HIGH"),
            ],
        )
    )

    result = compare_reports(base, head)

    assert result.status == "THREATS_DETECTED"
    assert result.exit_code == 1
    assert [item.severity for item in result.new_findings] == ["HIGH", "MEDIUM", "LOW"]
    assert "New blocking threats:** 3" in render_markdown(result)


def test_resolved_findings_are_counted(tmp_path: Path) -> None:
    base = load_report(
        report(
            tmp_path / "base.json",
            [finding(), finding(test_id="B607", source='run(["git"])')],
        )
    )
    head = load_report(report(tmp_path / "head.json", [finding()]))

    result = compare_reports(base, head)

    assert result.status == "PASSED"
    assert result.resolved_count == 1


def test_duplicate_findings_use_multiset_comparison(tmp_path: Path) -> None:
    item = finding()
    base = load_report(report(tmp_path / "base.json", [item]))
    head = load_report(report(tmp_path / "head.json", [item, item]))

    result = compare_reports(base, head)

    assert result.status == "THREATS_DETECTED"
    assert len(result.new_findings) == 1


def test_invalid_report_fails_closed(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="no results list"):
        load_report(invalid)


def test_report_with_scan_errors_fails_closed(tmp_path: Path) -> None:
    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text(
        json.dumps(
            {
                "errors": [
                    {
                        "filename": "amosclaud_bot/broken.py",
                        "reason": "syntax error while scanning",
                    }
                ],
                "results": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="contains scan errors"):
        load_report(incomplete)
