from pathlib import Path

import pytest

from amoscloud_ai.book import AmosclaudBook, BookError
from amoscloud_ai.book_failures import failure_records, record_failure


def make_book(tmp_path: Path) -> AmosclaudBook:
    root = tmp_path / "book"
    (root / "chapters").mkdir(parents=True)
    (root / "book.manifest.json").write_text('{"chapters": []}', encoding="utf-8")
    (root / "capabilities.json").write_text('{"capabilities": []}', encoding="utf-8")
    (root / "next-task.json").write_text('{}', encoding="utf-8")
    (root / "slapface.json").write_text('{}', encoding="utf-8")
    (root / "slapface.md").write_text("Slapface", encoding="utf-8")
    (root / "changes.jsonl").write_text("", encoding="utf-8")
    return AmosclaudBook(root)


def valid_record():
    return {
        "failure_id": "failure-test-001",
        "recorded_at": "2026-09-05T00:00:00+00:00",
        "change_id": "change-test-001",
        "actor": "chatgpt",
        "failure_kind": "book_missing_update",
        "expected": "Book ledger and chapter reflect the change",
        "actual": "Book ledger was not updated",
        "action_result": {"state": "FAIL", "reason": "missing_book_record"},
        "correction": "Added the missing Book record and chapter update",
        "verification": {"state": "PASS", "evidence": ["book gate"]},
        "lessons": ["Book changes must be prepared before completion or merge"],
    }


def test_failure_record_is_persistent_and_immutable_by_id(tmp_path):
    book = make_book(tmp_path)
    record_failure(book, valid_record())
    assert failure_records(book)[0]["failure_id"] == "failure-test-001"
    with pytest.raises(BookError, match="Duplicate failure_id"):
        record_failure(book, valid_record())


def test_failure_record_requires_complete_contract(tmp_path):
    book = make_book(tmp_path)
    record = valid_record()
    record.pop("lessons")
    with pytest.raises(BookError, match="lessons"):
        record_failure(book, record)
