"""Safe authoring helpers for Amosclaud Book Studio.

Book Studio is the editable companion to the public Word Book reader. It keeps
Markdown as the canonical source so humans and agents share the same chapter.
Graphics and 3D objects are represented with explicit Amosclaud directives
rather than opaque editor-only state.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from amoscloud_ai.book import AmosclaudBook, BookError
from amoscloud_ai.book_watchdog import secret_verdict


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_actor(actor: str) -> str:
    value = "".join(char if char.isalnum() or char in "._-:@" else "-" for char in str(actor or "editor"))
    return value.strip("-._")[:128] or "editor"


def _chapter_meta(book: AmosclaudBook, chapter_id: str) -> dict[str, Any]:
    normalized = str(chapter_id).zfill(2)
    for chapter in book.chapters():
        if chapter["id"] == normalized:
            if not chapter["available"]:
                raise BookError(f"Chapter {normalized} is registered but unavailable")
            return chapter
    raise BookError(f"Unknown Book chapter: {chapter_id}")


def save_chapter(
    book: AmosclaudBook,
    *,
    chapter_id: str,
    content: str,
    actor: str,
    summary: str,
) -> dict[str, Any]:
    """Publish one chapter after local secret and size checks.

    The raw chapter is never copied into the return payload. A previous version
    is saved only after the new content passes the same high-confidence secret
    policy, which prevents Book Studio history from becoming a credential dump.
    """

    source = str(content or "")
    if not source.strip():
        raise BookError("Book chapter content must not be empty")
    if len(source.encode("utf-8")) > 2_000_000:
        raise BookError("Book chapter content exceeds the 2 MB authoring limit")

    verdict = secret_verdict(source)
    if not verdict["allowed"]:
        kinds = sorted(
            {
                str(item.get("kind"))
                for item in verdict["findings"]
                if item.get("classification") in {"confirmed_secret", "probable_secret"}
            }
        )
        raise BookError(
            "Book Studio blocked publishing because high-confidence credential-like material "
            f"was detected ({', '.join(kinds) or 'credential'}). The value was not stored."
        )

    meta = _chapter_meta(book, chapter_id)
    target = (book.root / meta["path"]).resolve()
    try:
        target.relative_to(book.root.resolve())
    except ValueError as exc:
        raise BookError("Book chapter path escapes the Book root") from exc

    current = target.read_text(encoding="utf-8")
    current_verdict = secret_verdict(current)
    # Legacy unsafe Book content must not be duplicated into revision storage.
    may_snapshot = current_verdict["allowed"]

    actor_id = _safe_actor(actor)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    if may_snapshot:
        revision = book.runtime_path / "revisions" / meta["id"] / f"{timestamp}.md"
        revision.parent.mkdir(parents=True, exist_ok=True)
        revision.write_text(current, encoding="utf-8")

    temporary = target.with_suffix(target.suffix + ".studio.tmp")
    temporary.write_text(source.rstrip() + "\n", encoding="utf-8")
    os.replace(temporary, target)

    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    event = {
        "actor": actor_id,
        "chapter_id": meta["id"],
        "chapter_path": meta["path"],
        "summary": str(summary or "Book Studio chapter update")[:500],
        "saved_at": _now(),
        "sha256": digest,
        "warning_count": verdict["warning_count"],
        "revision_saved": may_snapshot,
    }
    book._refuse_secrets(event, operation="Book Studio save metadata")
    history = book.runtime_path / "studio.jsonl"
    history.parent.mkdir(parents=True, exist_ok=True)
    with history.open("a", encoding="utf-8") as handle:
        import json

        handle.write(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n")
    return event


def studio_tool_catalog() -> dict[str, Any]:
    """Describe Book Studio tools for both UI clients and AI agents."""

    return {
        "surface": "Amosclaud Book Studio",
        "canonical_format": "Markdown plus structured Amosclaud visual directives",
        "tabs": {
            "home": ["font", "size", "bold", "italic", "underline", "alignment", "headings", "lists"],
            "insert": ["table", "link", "callout", "drawing", "shape", "roadmap", "risk-register", "image"],
            "design": ["theme", "page-width", "cover", "print-pdf"],
            "graphics": ["paint-canvas", "diagram", "svg-shape", "roadmap", "risk-graphic"],
            "3d": ["agent-workstation-scene", "interactive-preview", "structured-3d-directive"],
        },
        "directives": {
            "3d": ':::amosclaud-3d scene="agent-workstation" caption="..."',
            "graphic": ':::amosclaud-graphic kind="roadmap" title="..."',
            "drawing_metadata": '<!-- amosclaud-graphic: {"kind":"drawing","source":"book-studio"} -->',
        },
        "agent_rule": "Agents read both prose and Amosclaud visual directives; visual editor state must never be the only source of meaning.",
        "security_rule": "Book Studio never publishes confirmed/probable credential material and never echoes the candidate secret in its result.",
    }
