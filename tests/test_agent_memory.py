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
        project="amosclaud",
        confidence=0.8,
    )
    assert stored["stored"] is True
    recalled = AgentMemory(tmp_path / "memory").recall(
        "safe database changes", project="amosclaud"
    )
    assert recalled[0]["id"] == stored["id"]
    assert recalled[0]["access_count"] == 1
    summary = memory.consolidate_day()
    assert summary["memories"] == 1
    summary_text = (
        tmp_path / "memory" / "daily" / f"{summary['day']}.md"
    ).read_text()
    assert "Database migration lesson" in summary_text
    assert "Confidence: `0.80`" in summary_text


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


def test_outcomes_adapt_confidence_and_retrieval(tmp_path):
    memory = AgentMemory(tmp_path / "memory")
    failed = memory.remember(
        kind="repair",
        title="Risky migration repair",
        content="Apply the database migration repair.",
        project="amosclaud",
        confidence=0.8,
    )
    successful = memory.remember(
        kind="repair",
        title="Verified migration repair",
        content="Apply the database migration repair with checksum verification.",
        project="amosclaud",
        confidence=0.6,
    )

    failed_update = memory.record_outcome(failed["id"], outcome="failure")
    successful_update = memory.record_outcome(successful["id"], outcome="success")

    assert failed_update["confidence"] == 0.4
    assert successful_update["confidence"] == 0.7

    recalled = memory.recall(
        "database migration repair",
        project="amosclaud",
        include_failures=False,
    )
    assert [item["id"] for item in recalled] == [successful["id"]]

    stats = memory.stats()
    assert stats["successful_lessons"] == 1
    assert stats["failed_lessons"] == 1
    assert stats["total_recalls"] == 1


def test_memory_migrates_existing_database(tmp_path):
    memory = AgentMemory(tmp_path / "memory")
    stored = memory.remember(
        kind="lesson",
        title="Backward compatible schema",
        content="Existing memory databases remain readable after upgrades.",
    )

    reopened = AgentMemory(tmp_path / "memory")
    recalled = reopened.recall("memory database upgrades")

    assert recalled[0]["id"] == stored["id"]
    assert recalled[0]["outcome"] == "unknown"
    assert recalled[0]["confidence"] == 0.5
