"""Persistent account-scoped synchronization for Amosclaud Book local-first clients."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

_ALLOWED_KINDS = {"book", "resume"}

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _hash_document(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

def ensure_schema(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS amosclaud_book_documents (
            id TEXT NOT NULL,
            owner_user_id INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('book','resume')),
            payload_json TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            revision INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (owner_user_id, id),
            FOREIGN KEY(owner_user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS amosclaud_book_sync_operations (
            operation_id TEXT PRIMARY KEY,
            owner_user_id INTEGER NOT NULL,
            document_id TEXT NOT NULL,
            result_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(owner_user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_amosclaud_book_documents_owner_updated
            ON amosclaud_book_documents(owner_user_id, updated_at);
    """)
    db.commit()

def _conflict(row: sqlite3.Row) -> dict[str, Any]:
    return {"status": "conflict", "server": {
        "id": row["id"], "kind": row["kind"], "payload": json.loads(row["payload_json"]),
        "serverRevision": row["revision"], "serverUpdatedAt": row["updated_at"],
        "contentSha256": row["content_sha256"],
    }}

def _remember(db: sqlite3.Connection, operation_id: str, user_id: int, document_id: str, result: dict[str, Any]) -> None:
    db.execute(
        "INSERT INTO amosclaud_book_sync_operations(operation_id,owner_user_id,document_id,result_json,created_at) VALUES(?,?,?,?,?)",
        (operation_id, user_id, document_id, json.dumps(result, ensure_ascii=False), _now()),
    )
    db.commit()

def apply_operation(db: sqlite3.Connection, *, user_id: int, operation_id: str, document_id: str,
                    operation: str, payload: dict[str, Any] | None = None,
                    base_server_revision: int | None = None) -> dict[str, Any]:
    """Apply one queued operation with idempotency and optimistic concurrency."""
    if not operation_id or len(operation_id) > 200:
        raise ValueError("Invalid operation id")
    if not document_id or len(document_id) > 200:
        raise ValueError("Invalid document id")
    if operation not in {"upsert", "delete"}:
        raise ValueError("Unsupported Book sync operation")
    ensure_schema(db)
    previous = db.execute(
        "SELECT result_json FROM amosclaud_book_sync_operations WHERE operation_id=? AND owner_user_id=?",
        (operation_id, user_id),
    ).fetchone()
    if previous:
        return json.loads(previous["result_json"])
    row = db.execute(
        "SELECT * FROM amosclaud_book_documents WHERE owner_user_id=? AND id=?", (user_id, document_id)
    ).fetchone()
    if row is not None and base_server_revision != row["revision"]:
        result = _conflict(row)
        _remember(db, operation_id, user_id, document_id, result)
        return result
    if row is None and base_server_revision not in (None, 0):
        result = {"status": "conflict", "server": None, "reason": "Server document no longer exists"}
        _remember(db, operation_id, user_id, document_id, result)
        return result
    if operation == "delete":
        if row is not None:
            db.execute("DELETE FROM amosclaud_book_documents WHERE owner_user_id=? AND id=?", (user_id, document_id))
        result = {"status": "synced", "documentId": document_id, "deleted": True, "serverRevision": None}
    else:
        if not isinstance(payload, dict):
            raise ValueError("Book upsert requires a payload")
        kind = str(payload.get("kind", "book"))
        if kind not in _ALLOWED_KINDS:
            raise ValueError("Unsupported Book document kind")
        payload = dict(payload)
        payload.pop("localOnly", None)
        updated = _now()
        revision = (row["revision"] + 1) if row is not None else 1
        digest = _hash_document(payload)
        encoded = json.dumps(payload, ensure_ascii=False)
        if row is None:
            db.execute("INSERT INTO amosclaud_book_documents(id,owner_user_id,kind,payload_json,content_sha256,revision,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                       (document_id, user_id, kind, encoded, digest, revision, updated, updated))
        else:
            db.execute("UPDATE amosclaud_book_documents SET kind=?,payload_json=?,content_sha256=?,revision=?,updated_at=? WHERE owner_user_id=? AND id=?",
                       (kind, encoded, digest, revision, updated, user_id, document_id))
        result = {"status": "synced", "documentId": document_id, "serverRevision": revision,
                  "serverUpdatedAt": updated, "contentSha256": digest, "payload": payload}
    _remember(db, operation_id, user_id, document_id, result)
    return result

def list_documents(db: sqlite3.Connection, *, user_id: int) -> list[dict[str, Any]]:
    ensure_schema(db)
    rows = db.execute("SELECT id,kind,payload_json,content_sha256,revision,created_at,updated_at FROM amosclaud_book_documents WHERE owner_user_id=? ORDER BY updated_at DESC", (user_id,)).fetchall()
    return [{"id": r["id"], "kind": r["kind"], "payload": json.loads(r["payload_json"]),
             "serverRevision": r["revision"], "serverUpdatedAt": r["updated_at"], "contentSha256": r["content_sha256"]} for r in rows]
