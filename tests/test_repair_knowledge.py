"""Contracts for verified repair memory and capability progression."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from amoscloud_ai.repair_knowledge import VerifiedRepairMemory, sanitize


def _reports(root: Path, *, failure: str = "Black would reformat src/app.py"):
    failure_log = root / "failure.log"
    candidate = root / "candidate.json"
    verification = root / "verification.json"
    failure_log.write_text(failure, encoding="utf-8")
    candidate.write_text(
        json.dumps(
            {
                "status": "candidate_applied",
                "changed_files": ["src/app.py", "tests/test_app.py"],
            }
        ),
        encoding="utf-8",
    )
    verification.write_text(
        json.dumps(
            {
                "status": "passed",
                "credential_free": True,
                "results": [
                    {"name": "flake8_critical", "returncode": 0},
                    {"name": "pytest_full", "returncode": 0},
                ],
            }
        ),
        encoding="utf-8",
    )
    return failure_log, candidate, verification


def test_novel_verified_technique_unlocks_one_level(tmp_path: Path) -> None:
    memory = VerifiedRepairMemory(tmp_path / "catalog.json")
    failure, candidate, verification = _reports(tmp_path)

    result = memory.learn_from_reports(
        failure_log=failure,
        candidate_report=candidate,
        verification_report=verification,
        source="CI",
        source_run_id="1",
    )

    assert result["novel"] is True
    assert result["level"] == 2
    assert result["unique_techniques"] == 1


def test_repeated_technique_does_not_unlock_another_level(tmp_path: Path) -> None:
    memory = VerifiedRepairMemory(tmp_path / "catalog.json")
    failure, candidate, verification = _reports(tmp_path)

    first = memory.learn_from_reports(
        failure_log=failure,
        candidate_report=candidate,
        verification_report=verification,
    )
    second = memory.learn_from_reports(
        failure_log=failure,
        candidate_report=candidate,
        verification_report=verification,
    )

    assert first["level"] == 2
    assert second["novel"] is False
    assert second["level"] == 2
    assert second["successful_reuses"] == 1


def test_failed_verification_never_unlocks_a_level(tmp_path: Path) -> None:
    memory = VerifiedRepairMemory(tmp_path / "catalog.json")
    failure, candidate, verification = _reports(tmp_path)
    payload = json.loads(verification.read_text(encoding="utf-8"))
    payload["status"] = "failed"
    payload["results"][0]["returncode"] = 1
    verification.write_text(json.dumps(payload), encoding="utf-8")

    result = memory.learn_from_reports(
        failure_log=failure,
        candidate_report=candidate,
        verification_report=verification,
    )

    assert result["learned"] is False
    assert result["level"] == 1
    assert result["failed_attempts"] == 1


def test_level_is_capped_at_five_and_requires_unique_techniques(tmp_path: Path) -> None:
    memory = VerifiedRepairMemory(tmp_path / "catalog.json")
    for index, failure in enumerate(
        (
            "Black would reformat src/app.py",
            "HTTP 401 authentication failed",
            "redirect_uri_mismatch in OAuth callback",
            "ModuleNotFoundError during pytest",
            "Docker build timed out",
        ),
        start=1,
    ):
        run = tmp_path / str(index)
        run.mkdir()
        files = _reports(run, failure=failure)
        memory.learn_from_reports(
            failure_log=files[0],
            candidate_report=files[1],
            verification_report=files[2],
        )

    status = memory.status()
    assert status["level"] == 5
    assert status["unique_techniques"] == 5


def test_catalog_redacts_secrets_and_stores_no_patch(tmp_path: Path) -> None:
    memory = VerifiedRepairMemory(tmp_path / "catalog.json")
    failure, candidate, verification = _reports(
        tmp_path,
        failure="API_KEY=secret-value HTTP 401 invalid or revoked",
    )

    memory.learn_from_reports(
        failure_log=failure,
        candidate_report=candidate,
        verification_report=verification,
    )
    catalog = (tmp_path / "catalog.json").read_text(encoding="utf-8")

    assert "secret-value" not in catalog
    assert "diff --git" not in catalog
    assert "patch" not in catalog.lower()
    assert "secret-value" not in sanitize("API_KEY=secret-value")


def test_recall_returns_only_verified_declarative_guidance(tmp_path: Path) -> None:
    memory = VerifiedRepairMemory(tmp_path / "catalog.json")
    failure, candidate, verification = _reports(tmp_path)
    memory.learn_from_reports(
        failure_log=failure,
        candidate_report=candidate,
        verification_report=verification,
    )

    matches = memory.recall("Black would reformat another Python file")
    context = memory.prompt_context(matches)

    assert len(matches) == 1
    assert "Do not copy old patches" in context
    assert "would-reformat" in context


def test_repair_report_is_learned_only_after_pass(tmp_path: Path) -> None:
    memory = VerifiedRepairMemory(tmp_path / "catalog.json")
    report = SimpleNamespace(
        final_verdict=SimpleNamespace(value="PASS"),
        changed_files=["config/app.json"],
        repairs=[SimpleNamespace(description="json-syntax", changed=True)],
        evidence=[SimpleNamespace(name="pytest", output="PASS", passed=True)],
    )

    result = memory.record_report(report, source_run_id="run-1")

    assert result["novel"] is True
    assert result["level"] == 2
