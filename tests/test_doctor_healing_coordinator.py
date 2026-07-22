from __future__ import annotations

import json
from pathlib import Path

from amoscloud_ai.repair_engine import AutonomousDecisionEngine, Verdict, recommendations
from amoscloud_ai.repair_engine.core import Finding, Severity


def test_doctor_accumulates_distinct_safe_repairs_before_verification(tmp_path: Path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("first   ", encoding="utf-8")
    second.write_text("second   ", encoding="utf-8")

    report = AutonomousDecisionEngine(
        tmp_path,
        max_attempts=4,
        memory_path=tmp_path / "memory.jsonl",
    ).run(apply=True)

    assert report.final_verdict == Verdict.PASS
    assert report.changed_files == ["first.txt", "second.txt"]
    assert first.read_text(encoding="utf-8") == "first\n"
    assert second.read_text(encoding="utf-8") == "second\n"
    assert len([item for item in report.evidence if item.name.startswith("Doctor healing cycle")]) >= 2


def test_doctor_rolls_back_whole_healing_session_when_critical_remains(tmp_path: Path) -> None:
    safe = tmp_path / "safe.txt"
    broken = tmp_path / "broken.py"
    safe.write_text("repair me   ", encoding="utf-8")
    broken.write_text("def broken(:\n", encoding="utf-8")

    report = AutonomousDecisionEngine(
        tmp_path,
        max_attempts=3,
        memory_path=tmp_path / "memory.jsonl",
    ).run(apply=True)

    assert report.final_verdict == Verdict.FAIL
    assert report.changed_files == []
    assert safe.read_text(encoding="utf-8") == "repair me   "
    assert any(item.name == "Rollback unverified healing session" for item in report.evidence)
    capability = next(
        item for item in report.evidence if item.name == "Doctor remaining capability requirements"
    )
    payload = json.loads(capability.output)
    assert any(item["finding_code"] == "python-syntax" for item in payload)
    assert any(item["human_required"] is True for item in payload)


def test_recommendations_identify_registered_and_missing_capabilities() -> None:
    items = recommendations(
        [
            Finding("json-syntax", "bad json", Severity.REPAIRABLE, "tasks.json", 2),
            Finding("python-syntax", "bad python", Severity.CRITICAL, "app.py", 1),
            Finding("unknown-problem", "unknown", Severity.CRITICAL, "x.bin"),
        ]
    )

    assert items[0].next_strategy == "verified-json-normalizer"
    assert items[0].human_required is False
    assert items[1].next_strategy == "semantic-code-repair"
    assert items[1].human_required is True
    assert items[2].next_strategy == "unregistered-repair-strategy"
