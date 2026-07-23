import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

from amoscloud_ai.agent_memory import AgentMemory


def _create_v1_database(root, *, with_memory=False):
    root.mkdir(parents=True, exist_ok=True)
    database = root / "memory.db"
    with sqlite3.connect(database) as db:
        db.executescript(
            """
            CREATE TABLE memories (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                tags TEXT NOT NULL,
                importance REAL NOT NULL,
                source_run_id TEXT,
                content_hash TEXT NOT NULL UNIQUE
            );
            CREATE VIRTUAL TABLE memory_search USING fts5(
                memory_id UNINDEXED, title, content, tags, tokenize='porter unicode61'
            );
            """
        )
        if with_memory:
            kind = "lesson"
            title = "Legacy migration lesson"
            content = "Preserve one global memory while upgrading the database."
            tags = ["migration"]
            digest = hashlib.sha256(
                json.dumps([kind, title, content, tags], sort_keys=True).encode()
            ).hexdigest()
            memory_id = f"mem_{digest[:20]}"
            db.execute(
                """INSERT INTO memories
                   (id,created_at,kind,title,content,tags,importance,source_run_id,content_hash)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    memory_id,
                    "2026-07-22T00:00:00+00:00",
                    kind,
                    title,
                    content,
                    json.dumps(tags),
                    0.8,
                    "legacy-run",
                    digest,
                ),
            )
            db.execute(
                "INSERT INTO memory_search(memory_id,title,content,tags) VALUES (?,?,?,?)",
                (memory_id, title, content, " ".join(tags)),
            )
    return database


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
    assert second["id"] == first["id"]
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
    root = tmp_path / "memory"
    _create_v1_database(root)

    memory = AgentMemory(root)
    stored = memory.remember(
        kind="lesson",
        title="Backward compatible schema",
        content="Existing memory databases remain readable after upgrades.",
    )
    recalled = memory.recall("memory database upgrades")

    assert recalled[0]["id"] == stored["id"]
    assert recalled[0]["outcome"] == "unknown"
    assert recalled[0]["confidence"] == 0.5


def test_migrated_global_memory_keeps_legacy_deduplication(tmp_path):
    root = tmp_path / "memory"
    _create_v1_database(root, with_memory=True)

    memory = AgentMemory(root)
    duplicate = memory.remember(
        kind="lesson",
        title="Legacy migration lesson",
        content="Preserve one global memory while upgrading the database.",
        tags=["migration"],
        importance=0.8,
        source_run_id="new-run",
    )

    assert duplicate["stored"] is False
    assert memory.stats()["memories"] == 1
    assert len(memory.recall("global memory upgrading")) == 1


def test_concurrent_legacy_schema_migration_is_serialized(tmp_path):
    root = tmp_path / "memory"
    database = _create_v1_database(root)

    def open_memory(_):
        return AgentMemory(root).stats()["memories"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(open_memory, range(8))) == [0] * 8

    with sqlite3.connect(database) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(memories)")}

    assert {
        "project",
        "confidence",
        "outcome",
        "access_count",
        "last_accessed_at",
        "updated_at",
    }.issubset(columns)
