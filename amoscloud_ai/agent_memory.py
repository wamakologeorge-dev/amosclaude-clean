"""Durable, searchable, folder-native memory for Amosclaud agents."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*\S+"),
    re.compile(r"\b(?:sk|ghp|github_pat)_[A-Za-z0-9_-]{12,}\b"),
)


def _sanitize(value: str, limit: int = 12_000) -> str:
    text = value.replace("\x00", " ")[:limit]
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


class AgentMemory:
    """Disk-backed episodic and semantic memory with full-text retrieval."""

    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.journals = self.root / "journals"
        self.summaries = self.root / "daily"
        self.journals.mkdir(parents=True, exist_ok=True)
        self.summaries.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "memory.db"
        self._lock = threading.Lock()
        self._initialize()

    @classmethod
    def for_repository(cls, repository: Path) -> "AgentMemory":
        configured = os.getenv("AMOSCLAUD_AGENT_MEMORY_HOME", "").strip()
        return cls(Path(configured) if configured else repository / ".amosclaud" / "memory")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS memories (
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
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_search USING fts5(
                    memory_id UNINDEXED, title, content, tags, tokenize='porter unicode61'
                );
                """)

    def remember(
        self,
        *,
        kind: str,
        title: str,
        content: str,
        tags: list[str] | None = None,
        importance: float = 0.5,
        source_run_id: str | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        clean_title = _sanitize(title, 300).strip()
        clean_content = _sanitize(content).strip()
        clean_tags = sorted(
            {_sanitize(tag, 80).strip().lower() for tag in (tags or []) if tag.strip()}
        )
        if not clean_title or not clean_content:
            raise ValueError("Memory title and content are required")
        digest = hashlib.sha256(
            json.dumps([kind, clean_title, clean_content, clean_tags], sort_keys=True).encode()
        ).hexdigest()
        memory_id = f"mem_{digest[:20]}"
        record = {
            "id": memory_id,
            "created_at": now.isoformat(),
            "kind": kind,
            "title": clean_title,
            "content": clean_content,
            "tags": clean_tags,
            "importance": max(0.0, min(float(importance), 1.0)),
            "source_run_id": source_run_id,
            "content_hash": digest,
        }
        with self._lock, self._connect() as db:
            inserted = db.execute(
                """INSERT OR IGNORE INTO memories
                   (id,created_at,kind,title,content,tags,importance,source_run_id,content_hash)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    memory_id,
                    record["created_at"],
                    kind,
                    clean_title,
                    clean_content,
                    json.dumps(clean_tags),
                    record["importance"],
                    source_run_id,
                    digest,
                ),
            ).rowcount
            if inserted:
                db.execute(
                    "INSERT INTO memory_search(memory_id,title,content,tags) VALUES (?,?,?,?)",
                    (memory_id, clean_title, clean_content, " ".join(clean_tags)),
                )
                journal = self.journals / f"{now:%Y-%m-%d}.jsonl"
                with journal.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, sort_keys=True) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
        record["stored"] = bool(inserted)
        return record

    def recall(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        terms = re.findall(r"[A-Za-z0-9_]{2,}", _sanitize(query, 1000))[:24]
        if not terms:
            return []
        expression = " OR ".join(f'"{term}"' for term in terms)
        with self._connect() as db:
            rows = db.execute(
                """SELECT m.*, bm25(memory_search) AS rank
                   FROM memory_search JOIN memories m ON m.id=memory_search.memory_id
                   WHERE memory_search MATCH ?
                   ORDER BY (bm25(memory_search) - (m.importance * 2.0)) ASC
                   LIMIT ?""",
                (expression, max(1, min(limit, 50))),
            ).fetchall()
        return [self._row(row) for row in rows]

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM memories ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [self._row(row) for row in rows]

    def consolidate_day(self, day: str | None = None) -> dict[str, Any]:
        day = day or f"{datetime.now(timezone.utc):%Y-%m-%d}"
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM memories WHERE created_at LIKE ? ORDER BY importance DESC, created_at",
                (f"{day}%",),
            ).fetchall()
        lines = [f"# Amosclaud learning summary — {day}", ""]
        for row in rows:
            lines.extend([f"## {row['title']}", "", row["content"], ""])
        path = self.summaries / f"{day}.md"
        temporary = path.with_suffix(".md.tmp")
        temporary.write_text("\n".join(lines), encoding="utf-8")
        temporary.replace(path)
        return {"day": day, "memories": len(rows), "path": str(path)}

    def stats(self) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT COUNT(*) count, COALESCE(SUM(LENGTH(content)),0) bytes FROM memories"
            ).fetchone()
        return {
            "memories": row["count"],
            "content_bytes": row["bytes"],
            "storage_bytes": sum(
                path.stat().st_size for path in self.root.rglob("*") if path.is_file()
            ),
            "root": str(self.root),
        }

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value.pop("rank", None)
        value["tags"] = json.loads(value["tags"])
        return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="amosclaud-agent-memory")
    parser.add_argument("--home", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    recall = commands.add_parser("recall")
    recall.add_argument("query")
    recall.add_argument("--limit", type=int, default=8)
    recent = commands.add_parser("recent")
    recent.add_argument("--limit", type=int, default=20)
    consolidate = commands.add_parser("consolidate")
    consolidate.add_argument("--day")
    commands.add_parser("stats")
    args = parser.parse_args(argv)
    memory = AgentMemory(
        args.home or Path(os.getenv("AMOSCLAUD_AGENT_MEMORY_HOME", "data/agent-memory"))
    )
    if args.command == "recall":
        result = memory.recall(args.query, args.limit)
    elif args.command == "recent":
        result = memory.recent(args.limit)
    elif args.command == "consolidate":
        result = memory.consolidate_day(args.day)
    else:
        result = memory.stats()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
