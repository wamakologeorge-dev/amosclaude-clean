"""Amosclaud Word Book: public living manual and repository-native engineering memory.

The repository representation under ``.Amosclaud/book`` is intentionally plain
JSON/JSONL/Markdown so Git, local Amosclaud installations, Desktop, SpaceCodeMe
and future MCP clients can consume the same contract without a GitHub-only API.
The Book is readable documentation first; repository-scoped Slapface runtime
state provides the watchdog behavior without turning the Book into a secret
store.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from amoscloud_ai.book_watchdog import secret_verdict

BOOK_ROOT_ENV = "AMOSCLAUD_BOOK_ROOT"
DEFAULT_BOOK_ROOT = Path(__file__).resolve().parents[1] / ".Amosclaud" / "book"
_SAFE_ACTOR = re.compile(r"[^A-Za-z0-9_.-]+")


class BookError(ValueError):
    """Raised when a Book operation violates the Book contract."""


class AmosclaudBook:
    """Read/write service over the portable Amosclaud Word Book representation."""

    def __init__(self, root: str | Path | None = None) -> None:
        configured = root or os.getenv(BOOK_ROOT_ENV)
        self.root = Path(configured).expanduser().resolve() if configured else DEFAULT_BOOK_ROOT
        self.manifest_path = self.root / "book.manifest.json"
        self.capabilities_path = self.root / "capabilities.json"
        self.changes_path = self.root / "changes.jsonl"
        self.next_task_path = self.root / "next-task.json"
        self.slapface_policy_path = self.root / "slapface.json"
        self.slapface_intro_path = self.root / "slapface.md"
        self.chapters_path = self.root / "chapters"
        self.runtime_path = self.root / ".runtime"
        self.progress_path = self.runtime_path / "progress"
        self.agents_path = self.runtime_path / "agents"

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise BookError(f"Required Book file is missing: {path}") from exc
        except json.JSONDecodeError as exc:
            raise BookError(f"Invalid Book JSON: {path}") from exc

    @staticmethod
    def _atomic_json(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, path)

    @staticmethod
    def _actor_id(actor: str) -> str:
        value = _SAFE_ACTOR.sub("-", actor.strip()).strip("-._")
        if not value:
            raise BookError("actor must contain at least one safe identifier character")
        return value[:128]

    @staticmethod
    def _refuse_secrets(value: Any, *, operation: str) -> None:
        """Keep raw credentials out of durable Book data.

        Suspicious-only findings remain non-blocking. Confirmed/probable
        credential material is rejected before any Book file is opened for
        writing, and the candidate value is never included in the exception.
        """
        payload = json.dumps(value, ensure_ascii=False, default=str)
        verdict = secret_verdict(payload)
        if not verdict["allowed"]:
            kinds = sorted(
                {
                    str(item.get("kind"))
                    for item in verdict["findings"]
                    if item.get("classification") in {"confirmed_secret", "probable_secret"}
                }
            )
            label = ", ".join(kinds) if kinds else "credential-like material"
            raise BookError(
                f"Book refused {operation}: high-confidence {label} was detected. "
                "The raw value was not stored. Use an environment/secret reference instead."
            )

    def manifest(self) -> dict[str, Any]:
        return self._load_json(self.manifest_path)

    def version(self) -> str:
        """Return a content hash representing the canonical portable Book state."""
        digest = hashlib.sha256()
        paths = [
            self.manifest_path,
            self.capabilities_path,
            self.next_task_path,
            self.slapface_policy_path,
            self.slapface_intro_path,
            self.changes_path,
        ]
        paths.extend(sorted(self.chapters_path.glob("*.md")))
        for path in paths:
            digest.update(path.relative_to(self.root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()

    def slapface_intro(self) -> dict[str, Any]:
        """Return the public Book preface used by humans and governed agents."""
        try:
            content = self.slapface_intro_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise BookError(f"Required Book file is missing: {self.slapface_intro_path}") from exc
        return {
            "id": "slapface",
            "title": "Slapface",
            "position": "preface-before-chapters",
            "public_readable": True,
            "path": self.slapface_intro_path.relative_to(self.root).as_posix(),
            "content": content,
            "policy": self._load_json(self.slapface_policy_path),
        }

    def chapters(self) -> list[dict[str, Any]]:
        manifest = self.manifest()
        result: list[dict[str, Any]] = []
        for chapter in manifest.get("chapters", []):
            item = dict(chapter)
            path = self.chapters_path / f"{chapter['id']}-{chapter['slug']}.md"
            item["available"] = path.exists()
            item["path"] = path.relative_to(self.root).as_posix()
            result.append(item)
        return result

    def chapter(self, chapter_id: str) -> dict[str, Any]:
        for chapter in self.chapters():
            if chapter["id"] == str(chapter_id).zfill(2):
                if not chapter["available"]:
                    raise BookError(f"Chapter {chapter['id']} is registered but not written yet")
                body = (self.root / chapter["path"]).read_text(encoding="utf-8")
                return {**chapter, "content": body}
        raise BookError(f"Unknown Book chapter: {chapter_id}")

    def capabilities(self) -> list[dict[str, Any]]:
        return list(self._load_json(self.capabilities_path).get("capabilities", []))

    def product(self, product_id: str) -> dict[str, Any]:
        normalized = product_id.casefold().replace("_", "-")
        for capability in self.capabilities():
            identifiers = {
                str(capability.get("id", "")).casefold(),
                str(capability.get("name", "")).casefold().replace(" ", "-"),
            }
            if normalized in identifiers:
                return capability
        raise BookError(f"Unknown Amosclaud product/capability: {product_id}")

    def changes(self, limit: int = 100) -> list[dict[str, Any]]:
        if limit < 1 or limit > 1000:
            raise BookError("limit must be between 1 and 1000")
        if not self.changes_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for raw in self.changes_path.read_text(encoding="utf-8").splitlines():
            if raw.strip():
                rows.append(json.loads(raw))
        return rows[-limit:]

    def next_task(self) -> dict[str, Any]:
        return self._load_json(self.next_task_path)

    def status(self) -> dict[str, Any]:
        chapters = self.chapters()
        capabilities = self.capabilities()
        counts: dict[str, int] = {}
        for capability in capabilities:
            status = str(capability.get("status", "unknown"))
            counts[status] = counts.get(status, 0) + 1
        manifest = self.manifest()
        return {
            "service": "Amosclaud Word Book",
            "schema_version": manifest.get("schema_version"),
            "book_version": self.version(),
            "public_readable": True,
            "book_roles": ["readme", "mini-word", "documentation", "guidelines", "vision", "engineering-memory"],
            "intro": {"id": "slapface", "title": "Slapface", "position": "before-chapters"},
            "chapter_count": len(chapters),
            "written_chapters": sum(1 for chapter in chapters if chapter["available"]),
            "capability_status_counts": counts,
            "change_count": len(self.changes(limit=1000)),
            "next_task": self.next_task(),
            "public_reading": bool(manifest.get("product_contract", {}).get("public_reading", True)),
            "slapface_preflight": bool(manifest.get("agent_contract", {}).get("slapface_preflight_required", False)),
            "truth_rule": "Book status describes recorded evidence; it is not proof of production health by itself.",
        }

    def complete_chapter(self, chapter_id: str, reader: str) -> dict[str, Any]:
        chapter = self.chapter(chapter_id)
        actor = self._actor_id(reader)
        path = self.progress_path / f"{actor}.json"
        current = self._load_json(path) if path.exists() else {"actor": actor, "completed": {}}
        completed = current.setdefault("completed", {})
        completed[chapter["id"]] = {
            "book_version": self.version(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        self._atomic_json(path, current)
        return current

    def agent_context(self, agent_id: str, chapter_ids: list[str] | None = None) -> dict[str, Any]:
        actor = self._actor_id(agent_id)
        requested = chapter_ids or list(self.manifest().get("agent_contract", {}).get("must_read_before_work", []))
        selected = []
        for chapter_id in requested:
            selected.append(self.chapter(chapter_id))
        snapshot = {
            "agent_id": actor,
            "book_version": self.version(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "slapface_intro": self.slapface_intro(),
            "chapters": selected,
            "capabilities": self.capabilities(),
            "next_task": self.next_task(),
            "change_rule": self.manifest().get("sync_contract", {}).get("rule"),
            "slapface_rule": self.manifest().get("watchdog_contract"),
        }
        self._refuse_secrets(snapshot, operation="agent context snapshot")
        self._atomic_json(self.agents_path / f"{actor}.json", snapshot)
        return snapshot

    def append_change(self, report: dict[str, Any]) -> dict[str, Any]:
        required = {"change_id", "actor", "summary", "files_changed", "chapters_updated", "verification"}
        missing = sorted(required.difference(report))
        if missing:
            raise BookError(f"Change report missing required fields: {', '.join(missing)}")
        if not report.get("files_changed"):
            raise BookError("files_changed must not be empty")
        if not report.get("chapters_updated"):
            raise BookError("chapters_updated must not be empty")
        self._refuse_secrets(report, operation="change report")
        valid_chapters = {chapter["id"] for chapter in self.chapters()}
        invalid = [str(value).zfill(2) for value in report["chapters_updated"] if str(value).zfill(2) not in valid_chapters]
        if invalid:
            raise BookError(f"Unknown chapters in change report: {', '.join(invalid)}")
        entry = dict(report)
        entry["actor"] = self._actor_id(str(entry["actor"]))
        entry.setdefault("reported_at", datetime.now(timezone.utc).isoformat())
        existing_ids = {str(row.get("change_id")) for row in self.changes(limit=1000)}
        if str(entry["change_id"]) in existing_ids:
            raise BookError(f"Duplicate change_id: {entry['change_id']}")
        self.changes_path.parent.mkdir(parents=True, exist_ok=True)
        with self.changes_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
        return entry

    def gate(self, changed_files: list[str], change_id: str | None = None) -> dict[str, Any]:
        """Determine whether a change has satisfied the mandatory Book-update contract."""
        normalized = [str(Path(path)).replace("\\", "/") for path in changed_files]
        meaningful = [
            path
            for path in normalized
            if path and not path.startswith(".Amosclaud/book/.runtime/")
        ]
        book_updated = any(path.startswith(".Amosclaud/book/") for path in meaningful)
        report = None
        if change_id:
            report = next((row for row in reversed(self.changes(limit=1000)) if str(row.get("change_id")) == change_id), None)
        eligible = bool(meaningful) and book_updated and (report is not None if change_id else True)
        reasons: list[str] = []
        if not meaningful:
            reasons.append("No meaningful changed files were supplied.")
        if meaningful and not book_updated:
            reasons.append("A meaningful Amosclaud change has no .Amosclaud/book update.")
        if change_id and report is None:
            reasons.append(f"No Book change report exists for change_id {change_id}.")
        return {
            "eligible_for_completion": eligible,
            "eligible_for_merge": eligible,
            "book_updated": book_updated,
            "change_report_found": report is not None if change_id else None,
            "reasons": reasons,
            "rule": "No meaningful Amosclaud change is eligible for completion or merge until its Book is updated.",
        }
