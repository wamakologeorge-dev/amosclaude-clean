from __future__ import annotations

import json
from pathlib import Path

import pytest

from amoscloud_ai.book import AmosclaudBook, BookError


REPO_ROOT = Path(__file__).resolve().parents[1]
BOOK_ROOT = REPO_ROOT / ".Amosclaud" / "book"


def test_repository_book_has_all_registered_chapters() -> None:
    book = AmosclaudBook(BOOK_ROOT)
    chapters = book.chapters()

    assert len(chapters) == 11
    assert all(chapter["available"] for chapter in chapters)
    assert book.chapter("1")["id"] == "01"
    assert "What Amosclaud Is" in book.chapter("01")["content"]


def test_book_status_is_evidence_aware() -> None:
    book = AmosclaudBook(BOOK_ROOT)
    status = book.status()

    assert status["service"] == "Amosclaud Word Book"
    assert status["written_chapters"] == status["chapter_count"] == 11
    assert len(status["book_version"]) == 64
    assert "not proof" in status["truth_rule"]


def test_book_gate_requires_book_update() -> None:
    book = AmosclaudBook(BOOK_ROOT)

    rejected = book.gate(["amoscloud_ai/agent.py"])
    accepted = book.gate(["amoscloud_ai/agent.py", ".Amosclaud/book/chapters/03-agent.md"])

    assert rejected["eligible_for_completion"] is False
    assert rejected["eligible_for_merge"] is False
    assert accepted["eligible_for_completion"] is True
    assert accepted["eligible_for_merge"] is True


def test_book_gate_can_require_change_report() -> None:
    book = AmosclaudBook(BOOK_ROOT)

    result = book.gate(
        ["amoscloud_ai/book.py", ".Amosclaud/book/changes.jsonl"],
        change_id="book-bootstrap-2026-08-31",
    )

    assert result["change_report_found"] is True
    assert result["eligible_for_completion"] is True


def test_human_progress_and_agent_copy_are_runtime_state(tmp_path: Path) -> None:
    source = BOOK_ROOT
    book_root = tmp_path / "book"
    book_root.mkdir()
    (book_root / "chapters").mkdir()

    for filename in ["book.manifest.json", "capabilities.json", "changes.jsonl", "next-task.json"]:
        (book_root / filename).write_bytes((source / filename).read_bytes())
    for chapter in (source / "chapters").glob("*.md"):
        (book_root / "chapters" / chapter.name).write_bytes(chapter.read_bytes())

    book = AmosclaudBook(book_root)
    progress = book.complete_chapter("01", "human-reader")
    context = book.agent_context("agent-1", ["01", "03"])

    assert "01" in progress["completed"]
    assert context["agent_id"] == "agent-1"
    assert [chapter["id"] for chapter in context["chapters"]] == ["01", "03"]
    assert (book_root / ".runtime" / "progress" / "human-reader.json").exists()
    assert (book_root / ".runtime" / "agents" / "agent-1.json").exists()


def test_change_report_rejects_unknown_chapter(tmp_path: Path) -> None:
    source = BOOK_ROOT
    book_root = tmp_path / "book"
    book_root.mkdir()
    (book_root / "chapters").mkdir()
    for filename in ["book.manifest.json", "capabilities.json", "changes.jsonl", "next-task.json"]:
        (book_root / filename).write_bytes((source / filename).read_bytes())
    for chapter in (source / "chapters").glob("*.md"):
        (book_root / "chapters" / chapter.name).write_bytes(chapter.read_bytes())

    book = AmosclaudBook(book_root)
    with pytest.raises(BookError, match="Unknown chapters"):
        book.append_change(
            {
                "change_id": "invalid-chapter",
                "actor": "agent",
                "summary": "test",
                "files_changed": ["x.py"],
                "chapters_updated": ["99"],
                "verification": {"state": "pending"},
            }
        )


def test_manifest_declares_bidirectional_contract() -> None:
    manifest = json.loads((BOOK_ROOT / "book.manifest.json").read_text(encoding="utf-8"))

    assert manifest["sync_contract"]["github_native"] is True
    assert manifest["sync_contract"]["amosclaud_native"] is True
    assert manifest["agent_contract"]["completion_requires_book_update"] is True
