from pathlib import Path

from amoscloud_ai.agentic_cloud_engine import (
    ENGINE_NAMES,
    LOG_SERVICE_NAMES,
    AmosclaudAgenticCloudEngine,
)


def test_agentic_cloud_engine_exposes_five_internal_engines(tmp_path: Path):
    assert len(ENGINE_NAMES) == 5
    assert len(LOG_SERVICE_NAMES) == 5
    assert ENGINE_NAMES[0] == "agent-1-receive-engine"
    assert ENGINE_NAMES[-1] == "agent-5-verification-engine"


def test_read_only_agent_run_reports_all_five_engines(tmp_path: Path, monkeypatch):
    (tmp_path / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "agentic-test")

    run = AmosclaudAgenticCloudEngine(tmp_path).run(
        "Inspect the repository and report evidence",
        "autonomous-check",
        {"apply_changes": False},
    )

    assert run.authorized_writes is False
    assert len(run.events) == 5
    assert [event.engine for event in run.events] == list(ENGINE_NAMES)
    assert run.changed_files == []
    assert run.plan
    assert (tmp_path / ".amosclaud" / "agent-logs" / f"{run.run_id}.jsonl").exists()
