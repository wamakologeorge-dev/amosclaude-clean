from __future__ import annotations

import json
import subprocess
from pathlib import Path

from amoscloud_ai.engineering_verification import EngineeringVerification, verification_contract


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def test_guidance_is_not_misreported_as_unverified_engineering() -> None:
    result = verification_contract(engineering=False)
    assert result == {"required": False, "status": "not-applicable", "verified": False}


def test_engineering_requires_retained_passing_report() -> None:
    assert verification_contract(engineering=True)["status"] == "pending"
    assert verification_contract(engineering=True)["verified"] is False
    failed = verification_contract(engineering=True, report={"status": "failed", "verification_id": "v1"})
    assert failed["verified"] is False
    passed = verification_contract(
        engineering=True,
        report={"status": "verified", "verification_id": "v2", "commit_sha": "abc"},
    )
    assert passed["verified"] is True
    assert passed["verification_id"] == "v2"


def test_reports_are_persisted_and_secret_output_is_redacted(tmp_path: Path, monkeypatch) -> None:
    verifier = EngineeringVerification(repository_root=tmp_path, report_root=tmp_path / "reports")
    monkeypatch.setattr(verifier, "current_commit", lambda: "abc123")
    monkeypatch.setattr(verifier, "_git", lambda *args: "main" if args[:2] == ("branch", "--show-current") else "")
    monkeypatch.setattr(
        verifier,
        "_run",
        lambda name, command, timeout: {
            "name": name,
            "status": "passed",
            "exit_code": 0,
            "duration_seconds": 0.01,
            "output": verifier._redact("API_KEY=private-value"),
        },
    )
    report = verifier.run()
    assert report["status"] == "verified"
    stored = json.loads((verifier.report_root / report["report_file"]).read_text(encoding="utf-8"))
    assert stored["summary"]["passed"] == 3
    assert all("private-value" not in item["output"] for item in stored["checks"])


def test_merge_ledger_never_marks_history_verified_without_report(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "README.md").write_text("first\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-m", "Initial platform")

    verifier = EngineeringVerification(repository_root=tmp_path, report_root=tmp_path / "reports")
    ledger = verifier.merge_results()
    assert ledger
    assert ledger[0]["files_changed"] == 1
    assert ledger[0]["verification_status"] == "historical-unverified"


def test_agent_verification_contract_blocks_unverified_engineering() -> None:
    pending = verification_contract(engineering=True)
    failed = verification_contract(
        engineering=True,
        report={"status": "failed", "verification_id": "v1"},
    )
    guidance = verification_contract(engineering=False)

    assert pending == {"required": True, "status": "pending", "verified": False}
    assert failed["required"] is True
    assert failed["verified"] is False
    assert guidance["status"] == "not-applicable"
