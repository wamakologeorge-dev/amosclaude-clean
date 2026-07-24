"""Codex Memory: a structured, browsable knowledge codex for the autonomous agent.

The codex organises :class:`~amoscloud_ai.agent_memory.AgentMemory` entries into
named *volumes* (one per repository plus a shared ``global`` volume) and
*chapters* (one per entry kind).  It backs the ``memory.recall`` and
``memory.store`` tools declared in the autonomous codex configuration and is
exposed through the ``/api/v1/autonomous-codex/memory`` API.
"""
from __future__ import annotations

import os
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

from amoscloud_ai.agent_memory import AgentMemory

CODEX_KINDS: tuple[str, ...] = ("decision", "lesson", "fact", "event", "task", "outcome")
GLOBAL_VOLUME = "global"
CHAPTER_TITLES: dict[str, str] = {
    "decision": "Decisions",
    "lesson": "Lessons",
    "fact": "Facts",
    "event": "Events",
    "task": "Tasks",
    "outcome": "Outcomes",
}

_memory_lock = threading.Lock()
_memory_cache: dict[str, AgentMemory] = {}


class CodexMemoryError(ValueError):
    """Raised when a codex memory request is invalid."""


def codex_memory_root() -> Path:
    configured = os.getenv("AMOSCLAUD_CODEX_MEMORY_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path("./data/codex-memory")


def get_codex_memory() -> AgentMemory:
    """Return the process-wide codex memory for the configured root."""
    root = codex_memory_root()
    key = str(root.resolve()) if root.exists() else str(root)
    with _memory_lock:
        memory = _memory_cache.get(key)
        if memory is None:
            memory = AgentMemory(root)
            _memory_cache[key] = memory
        return memory


def normalise_volume(scope: str | None) -> str:
    """Normalise a volume name (repository ``owner/name`` or ``global``)."""
    value = (scope or "").strip().lower()
    if not value:
        return GLOBAL_VOLUME
    value = re.sub(r"[^a-z0-9._/-]+", "-", value).strip("-/")
    return value[:200] or GLOBAL_VOLUME


def normalise_kind(kind: str | None) -> str:
    value = (kind or "").strip().lower()
    if value not in CODEX_KINDS:
        raise CodexMemoryError(
            f"kind must be one of: {', '.join(CODEX_KINDS)}"
        )
    return value


def store_entry(
    *,
    scope: str | None,
    kind: str,
    title: str,
    content: str,
    tags: list[str] | None = None,
    importance: float = 0.5,
    source: str | None = None,
    outcome: str = "unknown",
) -> dict[str, Any]:
    """Store one codex entry inside the given volume."""
    clean_title = (title or "").strip()
    clean_content = (content or "").strip()
    if not clean_title or not clean_content:
        raise CodexMemoryError("title and content are required")
    return get_codex_memory().remember(
        kind=normalise_kind(kind),
        title=clean_title,
        content=clean_content,
        tags=tags or [],
        importance=importance,
        source_run_id=source,
        project=normalise_volume(scope),
        outcome=outcome if outcome in {"unknown", "success", "failure"} else "unknown",
    )


def search(
    query: str,
    *,
    scope: str | None = None,
    kinds: list[str] | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Full-text recall across the codex, optionally scoped to one volume."""
    clean_kinds = [normalise_kind(kind) for kind in kinds] if kinds else None
    return get_codex_memory().recall(
        query,
        limit=max(1, min(limit, 50)),
        project=normalise_volume(scope) if scope else None,
        kinds=clean_kinds,
    )


def recent(*, scope: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    return get_codex_memory().recent(
        limit=max(1, min(limit, 200)),
        project=normalise_volume(scope) if scope else None,
    )


def volumes() -> list[dict[str, Any]]:
    """List codex volumes with entry counts and last activity."""
    memory = get_codex_memory()
    if not memory.database.exists():
        return []
    with sqlite3.connect(memory.database) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            """SELECT COALESCE(NULLIF(project, ''), ?) AS volume,
                      COUNT(*) AS entries,
                      MAX(created_at) AS last_entry_at
               FROM memories GROUP BY volume ORDER BY last_entry_at DESC""",
            (GLOBAL_VOLUME,),
        ).fetchall()
    return [dict(row) for row in rows]


def digest(scope: str | None = None, *, per_chapter: int = 6) -> dict[str, Any]:
    """Build a chaptered codex digest for a volume, plus rendered markdown."""
    volume = normalise_volume(scope)
    memory = get_codex_memory()
    per_chapter = max(1, min(per_chapter, 25))
    chapters: list[dict[str, Any]] = []
    if memory.database.exists():
        with sqlite3.connect(memory.database) as db:
            db.row_factory = sqlite3.Row
            for kind in CODEX_KINDS:
                rows = db.execute(
                    """SELECT title, content, tags, created_at, importance, outcome
                       FROM memories
                       WHERE kind = ? AND (project = ? OR (?='global' AND project=''))
                       ORDER BY importance DESC, created_at DESC LIMIT ?""",
                    (kind, volume, volume, per_chapter),
                ).fetchall()
                if rows:
                    chapters.append(
                        {
                            "kind": kind,
                            "title": CHAPTER_TITLES[kind],
                            "entries": [dict(row) for row in rows],
                        }
                    )
    lines = [f"# Codex — {volume}"]
    for chapter in chapters:
        lines.append(f"\n## {chapter['title']}")
        for entry in chapter["entries"]:
            summary = " ".join(str(entry["content"]).split())
            if len(summary) > 240:
                summary = summary[:240] + "…"
            lines.append(f"- **{entry['title']}** — {summary}")
    return {
        "volume": volume,
        "chapters": chapters,
        "entry_count": sum(len(chapter["entries"]) for chapter in chapters),
        "markdown": "\n".join(lines),
    }


def stats() -> dict[str, Any]:
    data = get_codex_memory().stats()
    data["volumes"] = len(volumes())
    data.pop("root", None)  # never leak filesystem paths through the API
    return data


def reset_cache_for_tests() -> None:
    with _memory_lock:
        _memory_cache.clear()
