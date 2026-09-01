"""Amosclaud Postortores native data engine.

Postortores is not a PostgreSQL wrapper.  It presents Amosclaud-native data
primitives (versioned state, append-only events, agent memory, verification
evidence and graph relations) behind one deterministic API.  SQLite is the
bootstrap persistence substrate for the first implementation so the service
can run locally and on physical Amosclaud machines without another database
server.  The public contract is intentionally storage-engine independent.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from .types import DataRecord, EvidenceRecord, EventRecord, MemoryRecord


class PostortoresEngine:
    """Durable Amosclaud-native multi-model data engine."""

    def __init__(self, path: str | Path = "postortores.db") -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _init_schema(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS state_records (
            namespace TEXT NOT NULL,
            key TEXT NOT NULL,
            version INTEGER NOT NULL,
            value_json TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY(namespace, key, version)
        );
        CREATE INDEX IF NOT EXISTS idx_state_latest
            ON state_records(namespace, key, version DESC);

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stream TEXT NOT NULL,
            event_type TEXT NOT NULL,
            actor TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_events_stream ON events(stream, id);

        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            embedding_json TEXT,
            content_hash TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_memories_owner ON memories(owner, id);

        CREATE TABLE IF NOT EXISTS evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            claim TEXT NOT NULL,
            status TEXT NOT NULL,
            proof_json TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_evidence_subject ON evidence(subject, id);

        CREATE TABLE IF NOT EXISTS graph_edges (
            source TEXT NOT NULL,
            relation TEXT NOT NULL,
            target TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY(source, relation, target)
        );

        CREATE TABLE IF NOT EXISTS leases (
            resource TEXT PRIMARY KEY,
            holder TEXT NOT NULL,
            expires_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        """
        with self._lock:
            self._db.executescript(schema)
            self._db.commit()

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    @classmethod
    def _hash(cls, value: Any) -> str:
        return hashlib.sha256(cls._json(value).encode("utf-8")).hexdigest()

    def put(self, record: DataRecord) -> DataRecord:
        """Append a new immutable version of a namespace/key record."""
        now = time.time()
        payload = record.value
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT MAX(version) AS version FROM state_records WHERE namespace=? AND key=?",
                    (record.namespace, record.key),
                ).fetchone()
                version = int(row["version"] or 0) + 1
                self._db.execute(
                    "INSERT INTO state_records(namespace,key,version,value_json,tags_json,content_hash,created_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (
                        record.namespace,
                        record.key,
                        version,
                        self._json(payload),
                        self._json(record.tags),
                        self._hash(payload),
                        now,
                    ),
                )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        return DataRecord(record.namespace, record.key, record.value, version, list(record.tags))

    def get(self, namespace: str, key: str, version: int | None = None) -> DataRecord | None:
        query = (
            "SELECT * FROM state_records WHERE namespace=? AND key=? AND version=?"
            if version is not None
            else "SELECT * FROM state_records WHERE namespace=? AND key=? ORDER BY version DESC LIMIT 1"
        )
        params: tuple[Any, ...] = (namespace, key, version) if version is not None else (namespace, key)
        row = self._db.execute(query, params).fetchone()
        if row is None:
            return None
        value = json.loads(row["value_json"])
        if self._hash(value) != row["content_hash"]:
            raise IOError("Postortores record integrity verification failed")
        return DataRecord(
            namespace=row["namespace"],
            key=row["key"],
            value=value,
            version=row["version"],
            tags=json.loads(row["tags_json"]),
        )

    def history(self, namespace: str, key: str) -> list[DataRecord]:
        rows = self._db.execute(
            "SELECT * FROM state_records WHERE namespace=? AND key=? ORDER BY version ASC",
            (namespace, key),
        ).fetchall()
        return [
            DataRecord(r["namespace"], r["key"], json.loads(r["value_json"]), r["version"], json.loads(r["tags_json"]))
            for r in rows
        ]

    def append_event(self, event: EventRecord) -> int:
        payload_hash = self._hash({"stream": event.stream, "type": event.event_type, "payload": event.payload})
        with self._lock:
            cursor = self._db.execute(
                "INSERT INTO events(stream,event_type,actor,payload_json,content_hash,created_at) VALUES(?,?,?,?,?,?)",
                (event.stream, event.event_type, event.actor, self._json(event.payload), payload_hash, time.time()),
            )
            self._db.commit()
            return int(cursor.lastrowid)

    def read_events(self, stream: str, after_id: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT * FROM events WHERE stream=? AND id>? ORDER BY id ASC LIMIT ?",
            (stream, after_id, limit),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "stream": r["stream"],
                "type": r["event_type"],
                "actor": r["actor"],
                "payload": json.loads(r["payload_json"]),
                "hash": r["content_hash"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def remember(self, memory: MemoryRecord) -> int:
        with self._lock:
            cursor = self._db.execute(
                "INSERT INTO memories(owner,content,metadata_json,embedding_json,content_hash,created_at) VALUES(?,?,?,?,?,?)",
                (
                    memory.owner,
                    memory.content,
                    self._json(memory.metadata),
                    self._json(memory.embedding) if memory.embedding is not None else None,
                    self._hash({"content": memory.content, "metadata": memory.metadata}),
                    time.time(),
                ),
            )
            self._db.commit()
            return int(cursor.lastrowid)

    @staticmethod
    def _cosine(a: Iterable[float], b: Iterable[float]) -> float | None:
        av, bv = list(a), list(b)
        if len(av) != len(bv) or not av:
            return None
        dot = sum(x * y for x, y in zip(av, bv))
        denom = math.sqrt(sum(x * x for x in av)) * math.sqrt(sum(y * y for y in bv))
        if not math.isfinite(denom) or denom == 0.0:
            return 0.0
        result = dot / denom
        return result if math.isfinite(result) else 0.0

    def search_memory(self, owner: str, query_embedding: list[float], limit: int = 10) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT * FROM memories WHERE owner=? AND embedding_json IS NOT NULL",
            (owner,),
        ).fetchall()
        scored = []
        for row in rows:
            embedding = json.loads(row["embedding_json"])
            score = self._cosine(query_embedding, embedding)
            if score is None:
                continue
            scored.append(
                {
                    "id": row["id"],
                    "content": row["content"],
                    "metadata": json.loads(row["metadata_json"]),
                    "score": score,
                }
            )
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:limit]

    def record_evidence(self, evidence: EvidenceRecord) -> int:
        accepted = {"planned", "changed", "executed", "verified", "blocked", "failed"}
        if evidence.status not in accepted:
            raise ValueError(f"invalid evidence status: {evidence.status}")
        with self._lock:
            cursor = self._db.execute(
                "INSERT INTO evidence(subject,claim,status,proof_json,content_hash,created_at) VALUES(?,?,?,?,?,?)",
                (
                    evidence.subject,
                    evidence.claim,
                    evidence.status,
                    self._json(evidence.proof),
                    self._hash({"subject": evidence.subject, "claim": evidence.claim, "status": evidence.status, "proof": evidence.proof}),
                    time.time(),
                ),
            )
            self._db.commit()
            return int(cursor.lastrowid)

    def evidence_for(self, subject: str) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT * FROM evidence WHERE subject=? ORDER BY id ASC", (subject,)
        ).fetchall()
        return [
            {
                "id": r["id"],
                "claim": r["claim"],
                "status": r["status"],
                "proof": json.loads(r["proof_json"]),
                "hash": r["content_hash"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def link(self, source: str, relation: str, target: str, metadata: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO graph_edges(source,relation,target,metadata_json,created_at) VALUES(?,?,?,?,?)",
                (source, relation, target, self._json(metadata or {}), time.time()),
            )
            self._db.commit()

    def neighbors(self, source: str, relation: str | None = None) -> list[dict[str, Any]]:
        if relation is None:
            rows = self._db.execute("SELECT * FROM graph_edges WHERE source=?", (source,)).fetchall()
        else:
            rows = self._db.execute(
                "SELECT * FROM graph_edges WHERE source=? AND relation=?", (source, relation)
            ).fetchall()
        return [
            {"target": r["target"], "relation": r["relation"], "metadata": json.loads(r["metadata_json"])}
            for r in rows
        ]

    def acquire_lease(self, resource: str, holder: str, ttl_seconds: float = 30.0) -> bool:
        """Acquire or renew a distributed-work lease using engine time."""
        now = time.time()
        expires = now + ttl_seconds
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute("SELECT holder, expires_at FROM leases WHERE resource=?", (resource,)).fetchone()
                if row and row["expires_at"] > now and row["holder"] != holder:
                    self._db.rollback()
                    return False
                self._db.execute(
                    "INSERT INTO leases(resource,holder,expires_at,updated_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(resource) DO UPDATE SET holder=excluded.holder, expires_at=excluded.expires_at, updated_at=excluded.updated_at",
                    (resource, holder, expires, now),
                )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
            return True

    def health(self) -> dict[str, Any]:
        try:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS _health_check (id INTEGER PRIMARY KEY)"
            )
            self._db.execute(
                "INSERT OR REPLACE INTO _health_check(id) VALUES(1)"
            )
            self._db.commit()
            ok = True
        except Exception:
            ok = False
        return {
            "service": "Amosclaud Postortores",
            "status": "ready" if ok else "unavailable",
            "storage": "sqlite-bootstrap",
            "native_contract": True,
            "path": self.path,
        }
