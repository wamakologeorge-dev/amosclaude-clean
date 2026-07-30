from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

import amosclaud_daily_memory_runner as memory_runner
from amoscloud_ai.api.routes import capability_memory_api, provider_api
from amoscloud_ai.repair_knowledge import VerifiedRepairMemory

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "daily-build.yml"


def _checks() -> list[dict[str, object]]:
    return [
        {"name": "doctor", "returncode": 0},
        {"name": "pytest", "returncode": 0},
    ]


def _learn(
    memory: VerifiedRepairMemory,
    evidence: str,
    changed_file: str,
    run_id: str,
) -> dict[str, object]:
    return memory.learn_verified(
        failure_evidence=evidence,
        changed_files=[changed_file],
        verification_results=_checks(),
        source="test",
        source_run_id=run_id,
    )


def test_unique_verified_techniques_unlock_one_level_each(tmp_path: Path) -> None:
    memory = VerifiedRepairMemory(tmp_path / "catalog.json")

    results = [
        _learn(memory, "trailing whitespace", "src/a.py", "run-1"),
        _learn(memory, "json syntax", "web/a.json", "run-2"),
        _learn(memory, "python syntax", "src/b.py", "run-3"),
        _learn(memory, "unpinned action", ".github/workflows/ci.yml", "run-4"),
    ]

    assert [result["level"] for result in results] == [2, 3, 4, 5]
    assert all(result["novel"] is True for result in results)
    assert memory.status()["max_level"] == 5


def test_repeated_known_fix_never_unlocks_another_level(tmp_path: Path) -> None:
    memory = VerifiedRepairMemory(tmp_path / "catalog.json")
    first = _learn(memory, "trailing whitespace", "src/a.py", "run-1")
    repeated = _learn(memory, "trailing whitespace", "src/a.py", "run-2")

    assert first["level"] == 2
    assert repeated["novel"] is False
    assert repeated["level"] == 2
    assert repeated["successful_reuses"] == 1


def test_failed_verification_does_not_enter_memory_or_unlock_level(
    tmp_path: Path,
) -> None:
    memory = VerifiedRepairMemory(tmp_path / "catalog.json")
    failure_log = tmp_path / "failure.log"
    candidate = tmp_path / "candidate.json"
    verification = tmp_path / "verification.json"
    failure_log.write_text("test failed", encoding="utf-8")
    candidate.write_text(
        json.dumps({"status": "candidate_applied", "changed_files": ["src/a.py"]}),
        encoding="utf-8",
    )
    verification.write_text(
        json.dumps(
            {
                "status": "failed",
                "credential_free": True,
                "results": [{"name": "pytest", "returncode": 1}],
            }
        ),
        encoding="utf-8",
    )

    result = memory.learn_from_reports(
        failure_log=failure_log,
        candidate_report=candidate,
        verification_report=verification,
    )

    assert result["learned"] is False
    assert result["level"] == 1
    assert result["failed_attempts"] == 1
    assert memory.recall("test failed", changed_files=["src/a.py"]) == []


def test_memory_catalog_redacts_credentials_and_does_not_store_patches(
    tmp_path: Path,
) -> None:
    catalog = tmp_path / "catalog.json"
    memory = VerifiedRepairMemory(catalog)
    _learn(
        memory,
        "authentication failed token=super_secret_value_123456789",
        "src/auth.py",
        "run-secret",
    )

    text = catalog.read_text(encoding="utf-8")
    assert "super_secret_value_123456789" not in text
    assert "[REDACTED]" not in text or "token=" not in text
    assert "diff --git" not in text


def test_memory_api_requires_service_key_and_all_green_checks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("AMOSCLAUD_MEMORY_ACCESS_KEY", "memory-test-key")
    monkeypatch.setattr(
        capability_memory_api,
        "default_catalog_path",
        lambda: tmp_path / "catalog.json",
    )

    with pytest.raises(HTTPException) as unauthorized:
        capability_memory_api.memory_status("Bearer wrong")
    assert unauthorized.value.status_code == 401

    request = capability_memory_api.MemoryLearnRequest(
        failure_evidence="json syntax",
        changed_files=["web/a.json"],
        verified=True,
        final_verdict="PASS",
        checks=[
            capability_memory_api.VerificationCheck(name="pytest", passed=False)
        ],
        source="test",
    )
    with pytest.raises(HTTPException) as rejected:
        capability_memory_api.memory_learn(request, "Bearer memory-test-key")
    assert rejected.value.status_code == 400


def test_memory_routes_are_mounted_on_provider_surface() -> None:
    paths = {getattr(route, "path", "") for route in provider_api.router.routes}

    assert "/provider/memory/status" in paths
    assert "/provider/memory/search" in paths
    assert "/provider/memory/learn" in paths
    assert "/provider/memory/failed" in paths
    assert "/provider/memory/export" in paths


def test_daily_workflow_clones_uses_and_persists_memory() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "ref: amosclaud-memory" in workflow
    assert "python amosclaud_daily_memory_runner.py" in workflow
    assert "AMOSCLAUD_MEMORY_ACCESS_KEY" in workflow
    assert "OLLAMA_API_KEY" in workflow
    assert "Persist sanitized memory mirror" in workflow
    assert "push origin HEAD:amosclaud-memory" in workflow


def test_runner_falls_back_to_cloned_memory_when_api_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    catalog = tmp_path / "catalog.json"
    monkeypatch.setenv("AMOSCLAUD_REPAIR_MEMORY_CATALOG", str(catalog))
    monkeypatch.setattr(memory_runner, "_REMOTE_REQUEST", lambda *_args: None)

    learned = memory_runner.memory_request(
        "learn",
        {
            "failure_evidence": "missing final newline",
            "changed_files": ["src/a.py"],
            "verified": True,
            "final_verdict": "PASS",
            "checks": [{"name": "pytest", "passed": True}],
            "source": "daily-agent",
            "source_run_id": "run-1",
        },
    )
    recalled = memory_runner.memory_request(
        "search",
        {
            "query": "missing final newline",
            "changed_files": ["src/b.py"],
            "limit": 4,
        },
    )

    assert learned and learned["level"] == 2
    assert recalled and recalled["matches"]
