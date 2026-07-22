from __future__ import annotations

from pathlib import Path

from amoscloud_ai.repair_engine import AutonomousRepairEngine, Doctor, Verdict


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
