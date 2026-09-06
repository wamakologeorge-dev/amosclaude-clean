"""Permanent failure-memory contract for the Amosclaud Word Book."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from amoscloud_ai.book import AmosclaudBook, BookError

FAILURE_FIELDS = {
    "failure_id",
    "recorded_at",
    "change_id",
    "actor",
    "failure_kind",
    "expected",
    "actual",
    "action_result",
    "correction",
    "verification",
    "lessons",
}


def failure_path(book: AmosclaudBook) -> Path:
    return book.root / "failures.jsonl"


def failure_records(book: AmosclaudBook, limit: int = 100) -> list[dict[str, Any]]:
    if limit < 1 or limit > 1000:
        raise BookError("limit must be between 1 and 1000")
    path = failure_path(book)
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows[-limit:]


def record_failure(book: AmosclaudBook, record: dict[str, Any]) -> dict[str, Any]:
    missing = sorted(FAILURE_FIELDS.difference(record))
    if missing:
        raise BookError(f"Failure record missing required fields: {', '.join(missing)}")
    if not record.get("failure_id") or not record.get("change_id"):
        raise BookError("failure_id and change_id are required")
    existing = {str(row.get("failure_id")) for row in failure_records(book, 1000)}
    if str(record["failure_id"]) in existing:
        raise BookError(f"Duplicate failure_id: {record['failure_id']}")
    book._refuse_secrets(record, operation="failure record")
    entry = dict(record)
    entry["recorded_at"] = entry.get("recorded_at") or datetime.now(timezone.utc).isoformat()
    path = failure_path(book)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
    return entry


def validate_failure_record(record: dict[str, Any]) -> None:
    missing = sorted(FAILURE_FIELDS.difference(record))
    if missing:
        raise BookError(f"Failure record missing required fields: {', '.join(missing)}")
