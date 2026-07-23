"""Durable, searchable, outcome-aware memory for Amosclaud agents."""

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
VALID_OUTCOMES = {"unknown", "success", "failure", "partial"}


def _sanitize(value: str, limit: int = 12_000) -> str:
    text = value.replace("\x00", " ")[:limit]
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def _clamp(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


class AgentMemory:
    """Disk-backed episodic and semantic memory with adaptive retrieval."""

    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.journals = self.root / "journals"
        self.summaries = self.root / "daily"
        self.journals.mkdir(parents=True, exist_ok=True)
        self.summaries.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "memory.db"
        self._lock = threading.RLock()
        self._initialize()

    @classmethod
    def for_repository(cls, repository: Path) -> "AgentMemory":
        configured = os.getenv("AMOSCLAUD_AGENT_MEMORY_HOME", "").strip()
        return cls(Path(configured) if configured else repository / ".amosclaud" / "memory")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
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
            columns = {row["name"] for row in db.execute("PRAGMA table_info(memories)")}
            migrations = {
                "project": "ALTER TABLE memories ADD COLUMN project TEXT NOT NULL DEFAULT ''",
                "confidence": "ALTER TABLE memories ADD COLUMN confidence REAL NOT NULL DEFAULT 0.5",
                "outcome": "ALTER TABLE memories ADD COLUMN outcome TEXT NOT NULL DEFAULT 'unknown'",
                "access_count": "ALTER TABLE memories ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0",
                "last_accessed_at": "ALTER TABLE memories ADD COLUMN last_accessed_at TEXT",
                "updated_at": "ALTER TABLE memories ADD COLUMN updated_at TEXT",
            }
            for column, statement in migrations.items():
                if column not in columns:
                    db.execute(statement)

    def remember(
        self,
        *,
        kind: str,
        title: str,
        content: str,
        tags: list[str] | None = None,
        importance: float = 0.5,
        source_run_id: str | None = None,
        project: str = "",
        confidence: float = 0.5,
        outcome: str = "unknown",
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        clean_kind = _sanitize(kind, 80).strip().lower()
        clean_title = _sanitize(title, 300).strip()
        clean_content = _sanitize(content).strip()
        clean_project = _sanitize(project, 200).strip().lower()
        clean_tags = sorted(
            {_sanitize(tag, 80).strip().lower() for tag in (tags or []) if tag.strip()}
        )
        if not clean_kind or not clean_title or not clean_content:
            raise ValueError("Memory kind, title, and content are required")
        if outcome not in VALID_OUTCOMES:
            raise ValueError(f"Outcome must be one of: {', '.join(sorted(VALID_OUTCOMES))}")

        digest = hashlib.sha256(
            json.dumps(
                [clean_kind, clean_title, clean_content, clean_tags, clean_project],
                sort_keys=True,
            ).encode()
        ).hexdigest()
        memory_id = f"mem_{digest[:20]}"
        record = {
            "id": memory_id,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "kind": clean_kind,
            "title": clean_title,
            "content": clean_content,
            "tags": clean_tags,
            "importance": _clamp(importance),
            "confidence": _clamp(confidence),
            "outcome": outcome,
            "project": clean_project,
            "source_run_id": source_run_id,
            "content_hash": digest,
            "access_count": 0,
            "last_accessed_at": None,
        }
        with self._lock, self._connect() as db:
            inserted = db.execute(
                """INSERT OR IGNORE INTO memories
                   (id,created_at,kind,title,content,tags,importance,source_run_id,
                    content_hash,project,confidence,outcome,access_count,last_accessed_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    memory_id,
                    record["created_at"],
                    clean_kind,
                    clean_title,
                    clean_content,
                    json.dumps(clean_tags),
                    record["importance"],
                    source_run_id,
                    digest,
                    clean_project,
                    record["confidence"],
                    outcome,
                    0,
                    None,
                    record["updated_at"],
                ),
            ).rowcount
            if inserted:
                db.execute(
                    "INSERT INTO memory_search(memory_id,title,content,tags) VALUES (?,?,?,?)",
                    (memory_id, clean_title, clean_content, " ".join(clean_tags)),
                )
                self._append_journal({"event": "remembered", **record})
        record["stored"] = bool(inserted)
        return record

    def recall(
        self,
        query: str,
        limit: int = 8,
        *,
        project: str | None = None,
        kinds: list[str] | None = None,
        include_failures: bool = True,
    ) -> list[dict[str, Any]]:
        terms = re.findall(r"[A-Za-z0-9_]{2,}", _sanitize(query, 1000))[:24]
        if not terms:
            return []
        expression = " OR ".join(f'"{term}"' for term in terms)
        conditions = ["memory_search MATCH ?"]
        parameters: list[Any] = [expression]
        if project:
            conditions.append("(m.project = ? OR m.project = '')")
            parameters.append(_sanitize(project, 200).strip().lower())
        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            conditions.append(f"m.kind IN ({placeholders})")
            parameters.extend(_sanitize(kind, 80).strip().lower() for kind in kinds)
        if not include_failures:
            conditions.append("m.outcome != 'failure'")
        parameters.append(max(1, min(limit, 50)))

        with self._lock, self._connect() as db:
            rows = db.execute(
                f"""SELECT m.*, bm25(memory_search) AS rank
                    FROM memory_search JOIN memories m ON m.id=memory_search.memory_id
                    WHERE {' AND '.join(conditions)}
                    ORDER BY (
                        bm25(memory_search)
                        - (m.importance * 2.0)
                        - (m.confidence * 1.5)
                        - (CASE m.outcome
                             WHEN 'success' THEN 1.25
                             WHEN 'partial' THEN 0.35
                             WHEN 'failure' THEN -0.75
                             ELSE 0 END)
                        - (MIN(m.access_count, 20) * 0.03)
                    ) ASC
                    LIMIT ?""",
                parameters,
            ).fetchall()
            ids = [row["id"] for row in rows]
            if ids:
                now = datetime.now(timezone.utc).isoformat()
                placeholders = ",".join("?" for _ in ids)
                db.execute(
                    f"""UPDATE memories
                        SET access_count=access_count+1, last_accessed_at=?, updated_at=COALESCE(updated_at, created_at)
                        WHERE id IN ({placeholders})""",
                    [now, *ids],
                )
                rows = db.execute(
                    f"SELECT * FROM memories WHERE id IN ({placeholders})",
                    ids,
                ).fetchall()
                by_id = {row["id"]: row for row in rows}
                rows = [by_id[memory_id] for memory_id in ids]
        return [self._row(row) for row in rows]

    def record_outcome(
        self,
        memory_id: str,
        *,
        outcome: str,
        confidence: float | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        if outcome not in VALID_OUTCOMES:
            raise ValueError(f"Outcome must be one of: {', '.join(sorted(VALID_OUTCOMES))}")
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown memory: {memory_id}")
            next_confidence = (
                _clamp(confidence)
                if confidence is not None
                else self._adjust_confidence(float(row["confidence"]), outcome)
            )
            db.execute(
                "UPDATE memories SET outcome=?, confidence=?, updated_at=? WHERE id=?",
                (outcome, next_confidence, now, memory_id),
            )
            updated = db.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        event = {
            "event": "outcome",
            "memory_id": memory_id,
            "outcome": outcome,
            "confidence": next_confidence,
            "note": _sanitize(note or "", 2000).strip(),
            "updated_at": now,
        }
        self._append_journal(event)
        return self._row(updated)

    def recent(
        self,
        limit: int = 20,
        *,
        project: str | None = None,
        outcome: str | None = None,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        parameters: list[Any] = []
        if project:
            conditions.append("project=?")
            parameters.append(_sanitize(project, 200).strip().lower())
        if outcome:
            if outcome not in VALID_OUTCOMES:
                raise ValueError(f"Outcome must be one of: {', '.join(sorted(VALID_OUTCOMES))}")
            conditions.append("outcome=?")
            parameters.append(outcome)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        parameters.append(max(1, min(limit, 200)))
        with self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM memories {where} ORDER BY created_at DESC LIMIT ?",
                parameters,
            ).fetchall()
        return [self._row(row) for row in rows]

    def consolidate_day(self, day: str | None = None) -> dict[str, Any]:
        day = day or f"{datetime.now(timezone.utc):%Y-%m-%d}"
        with self._connect() as db:
            rows = db.execute(
                """SELECT * FROM memories WHERE created_at LIKE ?
                   ORDER BY
                     CASE outcome WHEN 'success' THEN 0 WHEN 'partial' THEN 1
                                  WHEN 'unknown' THEN 2 ELSE 3 END,
                     importance DESC, confidence DESC, created_at""",
                (f"{day}%",),
            ).fetchall()
        lines = [f"# Amosclaud learning summary — {day}", ""]
        for row in rows:
            project = f" · project: {row['project']}" if row["project"] else ""
            lines.extend(
                [
                    f"## {row['title']}",
                    "",
                    f"- Kind: `{row['kind']}`{project}",
                    f"- Outcome: `{row['outcome']}`",
                    f"- Confidence: `{float(row['confidence']):.2f}`",
                    f"- Importance: `{float(row['importance']):.2f}`",
                    "",
                    row["content"],
                    "",
                ]
            )
        path = self.summaries / f"{day}.md"
        temporary = path.with_suffix(".md.tmp")
        temporary.write_text("\n".join(lines), encoding="utf-8")
        temporary.replace(path)
        return {"day": day, "memories": len(rows), "path": str(path)}

    def stats(self) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                """SELECT COUNT(*) count,
                          COALESCE(SUM(LENGTH(content)),0) bytes,
                          COALESCE(AVG(confidence),0) avg_confidence,
                          COALESCE(SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END),0) successes,
                          COALESCE(SUM(CASE WHEN outcome='failure' THEN 1 ELSE 0 END),0) failures,
                          COALESCE(SUM(access_count),0) recalls
                   FROM memories"""
            ).fetchone()
        return {
            "memories": row["count"],
            "content_bytes": row["bytes"],
            "average_confidence": round(float(row["avg_confidence"]), 4),
            "successful_lessons": row["successes"],
            "failed_lessons": row["failures"],
            "total_recalls": row["recalls"],
            "storage_bytes": sum(
                path.stat().st_size for path in self.root.rglob("*") if path.is_file()
            ),
            "root": str(self.root),
        }

    def _append_journal(self, record: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        journal = self.journals / f"{now:%Y-%m-%d}.jsonl"
        with journal.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _adjust_confidence(current: float, outcome: str) -> float:
        if outcome == "success":
            return _clamp(current + (1.0 - current) * 0.25)
        if outcome == "failure":
            return _clamp(current * 0.5)
        if outcome == "partial":
            return _clamp(current * 0.9)
        return _clamp(current)

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
    recall.add_argument("--project")
    recall.add_argument("--exclude-failures", action="store_true")

    recent = commands.add_parser("recent")
    recent.add_argument("--limit", type=int, default=20)
    recent.add_argument("--project")
    recent.add_argument("--outcome", choices=sorted(VALID_OUTCOMES))

    outcome = commands.add_parser("outcome")
    outcome.add_argument("memory_id")
    outcome.add_argument("result", choices=sorted(VALID_OUTCOMES))
    outcome.add_argument("--confidence", type=float)
    outcome.add_argument("--note")

    consolidate = commands.add_parser("consolidate")
    consolidate.add_argument("--day")
    commands.add_parser("stats")

    args = parser.parse_args(argv)
    memory = AgentMemory(
        args.home or Path(os.getenv("AMOSCLAUD_AGENT_MEMORY_HOME", "data/agent-memory"))
    )
    if args.command == "recall":
        result = memory.recall(
            args.query,
            args.limit,
            project=args.project,
            include_failures=not args.exclude_failures,
        )
    elif args.command == "recent":
        result = memory.recent(args.limit, project=args.project, outcome=args.outcome)
    elif args.command == "outcome":
        result = memory.record_outcome(
            args.memory_id,
            outcome=args.result,
            confidence=args.confidence,
            note=args.note,
        )
    elif args.command == "consolidate":
        result = memory.consolidate_day(args.day)
    else:
        result = memory.stats()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
