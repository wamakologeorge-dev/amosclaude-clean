from __future__ import annotations

import json
from pathlib import Path

from amoscloud_ai.repair_engine import AutonomousDecisionEngine, Doctor, Fixer, Severity, Verdict
from amoscloud_ai.repair_engine.json_repairs import normalize_json_text


def test_doctor_marks_json_comments_and_trailing_commas_repairable(tmp_path: Path) -> None:
    target = tmp_path / ".codesandbox" / "tasks.json"
    target.parent.mkdir(parents=True)
    target.write_text(
        '{\n'
        '  // CodeSandbox task configuration\n'
        '  "tasks": {\n'
        '    "start": {"command": "python app.py",},\n'
        '  },\n'
        '}\n',
        encoding="utf-8",
    )

    findings = Doctor(tmp_path).diagnose()
    json_findings = [item for item in findings if item.code == "json-syntax"]

    assert len(json_findings) == 1
    assert json_findings[0].severity == Severity.REPAIRABLE

    repairs = Fixer(tmp_path).apply(json_findings)

    assert any(item.code == "normalize-json" and item.changed for item in repairs)
    parsed = json.loads(target.read_text(encoding="utf-8"))
    assert parsed["tasks"]["start"]["command"] == "python app.py"
    assert Doctor.classify(Doctor(tmp_path).diagnose()) == Verdict.HEALTHY


def test_json_normalizer_preserves_comment_like_text_inside_strings() -> None:
    source = (
        '{\n'
        '  "url": "https://example.com/api//v1",\n'
        '  "pattern": "/* not a comment */",\n'
        '  "items": ["comma,}",], // actual comment\n'
        '}\n'
    )

    parsed = json.loads(normalize_json_text(source))

    assert parsed["url"] == "https://example.com/api//v1"
    assert parsed["pattern"] == "/* not a comment */"
    assert parsed["items"] == ["comma,}"]


def test_truly_ambiguous_broken_json_remains_critical_and_unchanged(tmp_path: Path) -> None:
    target = tmp_path / "broken.json"
    original = '{"tasks": { missing-value }}\n'
    target.write_text(original, encoding="utf-8")

    findings = Doctor(tmp_path).diagnose()
    json_findings = [item for item in findings if item.code == "json-syntax"]
    repairs = Fixer(tmp_path).apply(json_findings)

    assert json_findings[0].severity == Severity.CRITICAL
    assert repairs == []
    assert target.read_text(encoding="utf-8") == original


def test_decision_engine_repairs_codesandbox_json_end_to_end(tmp_path: Path) -> None:
    target = tmp_path / ".codesandbox" / "tasks.json"
    target.parent.mkdir(parents=True)
    target.write_text(
        '{\n'
        '  // accepted by CodeSandbox but rejected by strict JSON\n'
        '  "tasks": {"dev": {"command": "python -m app"}},\n'
        '}\n',
        encoding="utf-8",
    )

    report = AutonomousDecisionEngine(
        tmp_path,
        objective="repair `.codesandbox/tasks.json` safely",
        memory_path=tmp_path / "memory.jsonl",
    ).run(apply=True)

    assert report.final_verdict == Verdict.PASS
    assert report.changed_files == [".codesandbox/tasks.json"]
    assert json.loads(target.read_text(encoding="utf-8"))["tasks"]["dev"]["command"] == "python -m app"
    assert any(item.code == "normalize-json" and item.changed for item in report.repairs)
