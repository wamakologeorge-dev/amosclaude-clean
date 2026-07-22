from __future__ import annotations

from pathlib import Path

from amoscloud_ai.repair_engine import (
    AutonomousDecisionEngine,
    AutonomousRepairEngine,
    Doctor,
    Verdict,
)


def test_doctor_detects_and_fixer_repairs_safe_workflow_problem(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "name: CI  \n"
        "on: push\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    engine = AutonomousRepairEngine(tmp_path, required_files=["pyproject.toml"])
    report = engine.run(apply=True)

    assert report.final_verdict == Verdict.PASS
    repaired = workflow.read_text(encoding="utf-8")
    assert "actions/checkout@11d5960a326750d5838078e36cf38b85af677262" in repaired
    assert repaired.endswith("\n")
    assert "CI  \n" not in repaired


def test_doctor_never_autofixes_critical_python_syntax(tmp_path: Path) -> None:
    source = tmp_path / "broken.py"
    source.write_text("def broken(:\n    pass\n", encoding="utf-8")

    report = AutonomousRepairEngine(tmp_path).run(apply=True)

    assert report.diagnosis == Verdict.CRITICAL
    assert report.final_verdict == Verdict.FAIL
    assert source.read_text(encoding="utf-8") == "def broken(:\n    pass\n"


def test_missing_required_file_is_critical(tmp_path: Path) -> None:
    doctor = Doctor(tmp_path, required_files=["README.md"])
    findings = doctor.diagnose()

    assert Doctor.classify(findings) == Verdict.CRITICAL
    assert any(item.code == "missing-required-file" for item in findings)


def test_decision_engine_prioritizes_explicit_objective_file(tmp_path: Path) -> None:
    requested = tmp_path / "controlled-test.txt"
    unrelated = tmp_path / "README.md"
    requested.write_text("repair this line   \n", encoding="utf-8")
    unrelated.write_text("leave this line   ", encoding="utf-8")

    report = AutonomousDecisionEngine(
        tmp_path,
        objective="remove trailing whitespace in `controlled-test.txt`",
        memory_path=tmp_path / "memory.jsonl",
    ).run(apply=True)

    assert report.final_verdict == Verdict.PASS
    assert report.changed_files == ["controlled-test.txt"]
    assert requested.read_text(encoding="utf-8") == "repair this line\n"
    assert unrelated.read_text(encoding="utf-8") == "leave this line   "
    assert any("confidence=98%" in item.output for item in report.evidence)


def test_decision_engine_scans_named_text_file_outside_default_suffixes(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("value with spaces   ", encoding="utf-8")

    report = AutonomousDecisionEngine(
        tmp_path,
        objective="fix `notes.txt`",
        memory_path=tmp_path / "memory.jsonl",
    ).run(apply=True)

    assert report.final_verdict == Verdict.PASS
    assert target.read_text(encoding="utf-8") == "value with spaces\n"
    assert report.changed_files == ["notes.txt"]


def test_unverified_repair_is_rolled_back_and_not_publishable(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("repair me   ", encoding="utf-8")

    report = AutonomousDecisionEngine(
        tmp_path,
        objective="fix `target.txt`",
        commands=[["python", "-c", "raise SystemExit(7)"]],
        max_attempts=1,
        memory_path=tmp_path / "memory.jsonl",
    ).run(apply=True)

    assert report.final_verdict == Verdict.FAIL
    assert report.changed_files == []
    assert target.read_text(encoding="utf-8") == "repair me   "
    assert any(item.name == "Rollback unverified repair" and item.passed for item in report.evidence)


def test_critical_finding_blocks_decision_engine_repair(tmp_path: Path) -> None:
    target = tmp_path / "broken.py"
    target.write_text("def broken(:   \n", encoding="utf-8")

    report = AutonomousDecisionEngine(
        tmp_path,
        objective="fix `broken.py`",
        memory_path=tmp_path / "memory.jsonl",
    ).run(apply=True)

    assert report.final_verdict == Verdict.FAIL
    assert report.changed_files == []
    assert target.read_text(encoding="utf-8") == "def broken(:   \n"
