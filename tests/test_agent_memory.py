from amoscloud_ai.agent_memory import AgentMemory


def test_memory_persists_recalls_and_consolidates(tmp_path):
    memory = AgentMemory(tmp_path / "memory")
    stored = memory.remember(
        kind="engineering-run",
        title="Database migration lesson",
        content="Run checksum validation before applying a database migration.",
        tags=["database", "migration"],
        importance=0.9,
        source_run_id="run-1",
    )
    assert stored["stored"] is True
    recalled = AgentMemory(tmp_path / "memory").recall("safe database changes")
    assert recalled[0]["id"] == stored["id"]
    summary = memory.consolidate_day()
    assert summary["memories"] == 1
    assert (
        "Database migration lesson"
        in (tmp_path / "memory" / "daily" / f"{summary['day']}.md").read_text()
    )


def test_memory_redacts_secrets_and_deduplicates(tmp_path):
    memory = AgentMemory(tmp_path / "memory")
    first = memory.remember(
        kind="lesson",
        title="Credential handling",
        content="API_KEY=super-private-value must never enter logs",
    )
    second = memory.remember(
        kind="lesson",
        title="Credential handling",
        content="API_KEY=super-private-value must never enter logs",
    )
    assert first["stored"] is True
    assert second["stored"] is False
    assert "super-private-value" not in memory.recent()[0]["content"]
    assert memory.stats()["memories"] == 1
