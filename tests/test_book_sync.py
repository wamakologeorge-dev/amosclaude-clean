from __future__ import annotations

import sqlite3

from amoscloud_ai.book_sync import apply_operation, list_documents


def _db() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
    db.execute("INSERT INTO users(id) VALUES (7)")
    return db


def test_book_sync_is_idempotent_and_advances_revision() -> None:
    db = _db()
    first = apply_operation(
        db,
        user_id=7,
        operation_id="op-1",
        document_id="resume-1",
        operation="upsert",
        payload={"id": "resume-1", "kind": "resume", "title": "CV", "content": "v1"},
        base_server_revision=None,
    )
    assert first["status"] == "synced"
    assert first["serverRevision"] == 1

    retry = apply_operation(
        db,
        user_id=7,
        operation_id="op-1",
        document_id="resume-1",
        operation="upsert",
        payload={"id": "resume-1", "kind": "resume", "title": "CV", "content": "v1"},
        base_server_revision=None,
    )
    assert retry == first

    second = apply_operation(
        db,
        user_id=7,
        operation_id="op-2",
        document_id="resume-1",
        operation="upsert",
        payload={"id": "resume-1", "kind": "resume", "title": "CV", "content": "v2"},
        base_server_revision=1,
    )
    assert second["serverRevision"] == 2


def test_book_sync_returns_conflict_without_overwrite() -> None:
    db = _db()
    apply_operation(
        db,
        user_id=7,
        operation_id="op-1",
        document_id="book-1",
        operation="upsert",
        payload={"id": "book-1", "kind": "book", "title": "Plan", "content": "server"},
        base_server_revision=None,
    )
    conflict = apply_operation(
        db,
        user_id=7,
        operation_id="op-2",
        document_id="book-1",
        operation="upsert",
        payload={"id": "book-1", "kind": "book", "title": "Plan", "content": "local"},
        base_server_revision=0,
    )
    assert conflict["status"] == "conflict"
    assert conflict["server"]["payload"]["content"] == "server"
    assert list_documents(db, user_id=7)[0]["payload"]["content"] == "server"
