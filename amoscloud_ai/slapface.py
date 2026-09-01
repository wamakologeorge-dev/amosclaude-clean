"""Slapface: fail-closed Amosclaud Book continuity and secret-leak preflight."""
from __future__ import annotations

import hashlib
import math
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from amoscloud_ai.book import AmosclaudBook, BookError

DEFAULT_SCOPE = "default"
_SAFE_SCOPE = re.compile(r"[^A-Za-z0-9_.-]+")
_SECRET_NAME = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?key|auth[_-]?token|bearer[_-]?token|"
    r"client[_-]?secret|secret[_-]?key|token|password|passwd|private[_-]?key)\b"
)
_ASSIGNMENT = re.compile(
    r"(?ix)\b(?P<name>api[_-]?key|access[_-]?key|auth[_-]?token|bearer[_-]?token|"
    r"client[_-]?secret|secret[_-]?key|token|password|passwd|private[_-]?key|"
    r"openai[_-]?api[_-]?key|github[_-]?token|stripe[_-]?secret[_-]?key)\b"
    r"\s*(?:=|:)\s*[\"']?(?P<value>[A-Za-z0-9_./+=:@-]{12,})[\"']?"
)
_PROVIDER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}\b")),
    ("github", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b")),
    ("stripe", re.compile(r"\b(?:sk_live_|rk_live_)[A-Za-z0-9]{16,}\b")),
    ("slack", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("google", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b")),
    ("aws", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
)
_PLACEHOLDER_MARKERS = (
    "...", "<", ">", "example", "sample", "dummy", "placeholder", "replace",
    "changeme", "change-me", "your_", "your-", "not-a-real", "not_real",
    "fake", "redacted", "xxxx", "test-token", "test_key", "test-key",
)
_TEXT_SUFFIXES = {
    ".cfg", ".conf", ".css", ".env", ".go", ".html", ".ini", ".java", ".js",
    ".json", ".jsx", ".md", ".mjs", ".properties", ".py", ".rb", ".rs", ".sh",
    ".toml", ".ts", ".tsx", ".txt", ".xml", ".yaml", ".yml",
}
_SKIP_DIRS = {
    ".git", ".hg", ".svn", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "__pycache__", "node_modules", "venv", ".venv", "dist", "build", ".aicode",
}
_VERIFIED_STATES = {"verified", "passed", "completed", "success", "succeeded"}


class SlapfaceError(BookError):
    """Raised when a Slapface operation violates the continuity contract."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = Counter(value)
    size = len(value)
    return -sum((count / size) * math.log2(count / size) for count in counts.values())


def _looks_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    if not lowered or any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
        return True
    compact = re.sub(r"[^a-z0-9]", "", lowered)
    return len(compact) >= 8 and len(set(compact)) <= 3


def _redacted(value: str) -> str:
    if len(value) <= 8:
        return "••••"
    return f"{value[:4]}…{value[-4:]}"


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:16]


class Slapface:
    """Book-backed preflight that blocks unfinished work and high-confidence leaks."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.book = AmosclaudBook(root)
        self.root = self.book.root
        self.policy_path = self.root / "slapface.json"
        self.runtime_path = self.root / ".runtime" / "slapface"

    @staticmethod
    def _scope_id(scope: str | None) -> str:
        prepared = (scope or DEFAULT_SCOPE).strip() or DEFAULT_SCOPE
        safe = _SAFE_SCOPE.sub("-", prepared).strip("-._")
        return (safe or DEFAULT_SCOPE)[:128]

    def policy(self) -> dict[str, Any]:
        return self.book._load_json(self.policy_path)

    def _state_path(self, scope: str | None) -> Path:
        return self.runtime_path / f"{self._scope_id(scope)}.json"

    def _load_state(self, scope: str | None) -> dict[str, Any]:
        path = self._state_path(scope)
        if not path.exists():
            return {
                "schema_version": 1,
                "scope": self._scope_id(scope),
                "status": "clear",
                "active_handoff": None,
                "history": [],
                "updated_at": _utcnow(),
            }
        return self.book._load_json(path)

    def _save_state(self, scope: str | None, state: dict[str, Any]) -> dict[str, Any]:
        prepared = dict(state)
        prepared["scope"] = self._scope_id(scope)
        prepared["updated_at"] = _utcnow()
        self.book._atomic_json(self._state_path(scope), prepared)
        return prepared

    def _chapter_link(self, chapter_id: str) -> str:
        chapter = self.book.chapter(chapter_id)
        return f"/api/v1/book/reader/content#chapter={chapter['id']}"

    def status(self, scope: str | None = None) -> dict[str, Any]:
        state = self._load_state(scope)
        active = state.get("active_handoff")
        blocked = state.get("status") == "blocked" and isinstance(active, dict)
        policy = self.policy()
        return {
            "service": "Amosclaud Book Slapface",
            "scope": self._scope_id(scope),
            "blocked": blocked,
            "work_allowed": not blocked,
            "owner_bypass_allowed": False,
            "policy": policy,
            "active_handoff": active if blocked else None,
            "message": policy.get("blocked_message") if blocked else policy.get("clear_message"),
        }

    @staticmethod
    def scan_text(text: str, *, path: str = "<text>") -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        def add(
            *,
            value: str,
            detector: str,
            provider: str | None,
            confidence: float,
            line_number: int,
            context_name: str | None = None,
        ) -> None:
            if _looks_placeholder(value):
                return
            identity = (path, _fingerprint(value))
            if identity in seen:
                return
            seen.add(identity)
            blocking = confidence >= 0.92
            findings.append(
                {
                    "path": path,
                    "line": line_number,
                    "classification": (
                        "high_confidence_secret_exposure"
                        if blocking
                        else "suspicious_secret_like_value"
                    ),
                    "blocking": blocking,
                    "confidence": round(confidence, 2),
                    "provider": provider,
                    "context_name": context_name,
                    "detector": detector,
                    "preview": _redacted(value),
                    "fingerprint": _fingerprint(value),
                    "raw_value_exposed": False,
                }
            )

        for line_number, line in enumerate(text.splitlines(), 1):
            for provider, pattern in _PROVIDER_PATTERNS:
                for match in pattern.finditer(line):
                    add(
                        value=match.group(0),
                        detector="provider-format",
                        provider=provider,
                        confidence=0.99,
                        line_number=line_number,
                    )

            for match in _ASSIGNMENT.finditer(line):
                name = match.group("name")
                value = match.group("value")
                if _looks_placeholder(value):
                    continue
                entropy = _shannon_entropy(value)
                mixed = bool(re.search(r"[A-Za-z]", value) and re.search(r"\d", value))
                confidence = 0.62
                if _SECRET_NAME.search(name):
                    confidence += 0.12
                if len(value) >= 24:
                    confidence += 0.08
                if len(value) >= 32:
                    confidence += 0.04
                if entropy >= 3.5:
                    confidence += 0.05
                if entropy >= 4.0:
                    confidence += 0.04
                if mixed:
                    confidence += 0.03
                add(
                    value=value,
                    detector="secret-context-and-entropy",
                    provider=None,
                    confidence=min(confidence, 0.98),
                    line_number=line_number,
                    context_name=name,
                )

        blocking = [item for item in findings if item["blocking"]]
        warnings = [item for item in findings if not item["blocking"]]
        return {
            "path": path,
            "blocked": bool(blocking),
            "blocking_count": len(blocking),
            "warning_count": len(warnings),
            "findings": findings,
            "rule": (
                "Only high-confidence credential evidence blocks. "
                "Placeholders and lower-confidence secret-like values do not."
            ),
        }

    @classmethod
    def scan_workspace(
        cls,
        workspace: str | Path,
        *,
        max_files: int = 5000,
        max_bytes_per_file: int = 1_000_000,
    ) -> dict[str, Any]:
        root = Path(workspace).resolve()
        findings: list[dict[str, Any]] = []
        scanned = 0
        skipped = 0
        for path in root.rglob("*"):
            if scanned >= max_files:
                break
            if not path.is_file():
                continue
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue
            if any(part in _SKIP_DIRS for part in relative.parts):
                continue
            if path.name.startswith(".env") or path.suffix.lower() in _TEXT_SUFFIXES:
                try:
                    if path.stat().st_size > max_bytes_per_file:
                        skipped += 1
                        continue
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    skipped += 1
                    continue
                scanned += 1
                result = cls.scan_text(text, path=relative.as_posix())
                findings.extend(result["findings"])
        blocking = [item for item in findings if item["blocking"]]
        return {
            "workspace": str(root),
            "blocked": bool(blocking),
            "scanned_files": scanned,
            "skipped_files": skipped,
            "scan_limit_reached": scanned >= max_files,
            "blocking_count": len(blocking),
            "warning_count": len(findings) - len(blocking),
            "findings": findings,
        }

    def record_handoff(
        self,
        *,
        scope: str | None,
        agent_id: str,
        chapter_id: str,
        next_line: str,
        risk: str,
        missing_pieces: Iterable[str],
        required_paths: Iterable[str] = (),
        source: str = "amosclaud",
        kind: str = "unfinished_work",
        handoff_id: str | None = None,
    ) -> dict[str, Any]:
        chapter = self.book.chapter(chapter_id)
        pieces = [str(item).strip() for item in missing_pieces if str(item).strip()]
        if not next_line.strip():
            raise SlapfaceError("next_line must not be empty")
        if not risk.strip():
            raise SlapfaceError("risk must not be empty")
        if not pieces:
            raise SlapfaceError("missing_pieces must not be empty")
        state = self._load_state(scope)
        current = state.get("active_handoff")
        if state.get("status") == "blocked" and current:
            raise SlapfaceError(
                f"Scope already has unresolved Slapface handoff {current.get('handoff_id')}"
            )
        active = {
            "handoff_id": handoff_id or f"slap-{uuid.uuid4().hex[:16]}",
            "kind": kind,
            "agent_id": self.book._actor_id(agent_id),
            "chapter_id": chapter["id"],
            "chapter_title": chapter["title"],
            "chapter_link": self._chapter_link(chapter["id"]),
            "next_line": next_line.strip(),
            "risk": risk.strip(),
            "missing_pieces": pieces,
            "required_paths": sorted(
                {
                    str(Path(item)).replace("\\", "/")
                    for item in required_paths
                    if str(item).strip()
                }
            ),
            "source": source.strip() or "amosclaud",
            "created_at": _utcnow(),
            "owner_bypass_allowed": False,
        }
        state["status"] = "blocked"
        state["active_handoff"] = active
        state.setdefault("history", []).append(
            {"event": "blocked", "handoff_id": active["handoff_id"], "at": _utcnow()}
        )
        self._save_state(scope, state)
        return self.status(scope)

    def _ensure_secret_handoff(
        self,
        *,
        scope: str | None,
        agent_id: str,
        scan: dict[str, Any],
        source: str,
    ) -> dict[str, Any]:
        state = self._load_state(scope)
        if state.get("status") == "blocked" and state.get("active_handoff"):
            return self.status(scope)
        blocking = [item for item in scan.get("findings", []) if item.get("blocking")]
        paths = sorted({str(item.get("path")) for item in blocking if item.get("path")})
        fingerprints = sorted(
            {str(item.get("fingerprint")) for item in blocking if item.get("fingerprint")}
        )
        handoff_id = (
            "secret-"
            + hashlib.sha256("|".join(fingerprints).encode("utf-8")).hexdigest()[:16]
        )
        return self.record_handoff(
            scope=scope,
            agent_id=agent_id,
            chapter_id="09",
            next_line="Remove the exposed credential material before resuming repository work.",
            risk=(
                "A high-confidence API key or token exposure can grant unauthorized access. "
                "Continuing work may spread the credential into commits, logs, artifacts, or deployments."
            ),
            missing_pieces=[
                "Remove the credential value from tracked files and replace it with a safe placeholder or secret-manager reference.",
                "Rotate or revoke the exposed credential outside the repository when the provider supports rotation.",
                "Check relevant history, logs, generated artifacts, and deployment configuration for additional exposure.",
                "Record and verify the repair in the Amosclaud Book before resolving Slapface.",
            ],
            required_paths=paths,
            source=source,
            kind="secret_exposure",
            handoff_id=handoff_id,
        )

    def remediation_allowed(
        self,
        *,
        scope: str | None,
        handoff_id: str | None,
        mode: str,
        target_path: str | None = None,
    ) -> bool:
        state = self._load_state(scope)
        active = state.get("active_handoff")
        if state.get("status") != "blocked" or not isinstance(active, dict):
            return True
        if not handoff_id or handoff_id != active.get("handoff_id"):
            return False
        if mode.strip().lower() not in {"fix", "write"}:
            return False
        required_paths = {str(item) for item in active.get("required_paths") or []}
        if target_path and required_paths:
            normalized = str(Path(target_path)).replace("\\", "/")
            return normalized in required_paths
        return True

    def preflight(
        self,
        *,
        workspace: str | Path | None,
        scope: str | None,
        agent_id: str,
        objective: str,
        mode: str,
        source: str = "amosclaud",
        handoff_id: str | None = None,
        scan_secrets: bool = True,
    ) -> dict[str, Any]:
        actor = self.book._actor_id(agent_id)
        scan: dict[str, Any] | None = None
        if workspace is not None and scan_secrets:
            scan = self.scan_workspace(workspace)
            if scan.get("blocked"):
                self._ensure_secret_handoff(
                    scope=scope,
                    agent_id=actor,
                    scan=scan,
                    source=source,
                )

        status = self.status(scope)
        if not status["blocked"]:
            return {
                **status,
                "objective": objective,
                "mode": mode,
                "source": source,
                "secret_scan": scan,
                "remediation": False,
            }

        remediation = self.remediation_allowed(
            scope=scope,
            handoff_id=handoff_id,
            mode=mode,
        )
        if remediation:
            return {
                **status,
                "work_allowed": True,
                "blocked": True,
                "objective": objective,
                "mode": mode,
                "source": source,
                "secret_scan": scan,
                "remediation": True,
                "message": (
                    "Slapface remediation only: repair and verify the active handoff. "
                    "The original task remains blocked."
                ),
            }
        return {
            **status,
            "work_allowed": False,
            "objective": objective,
            "mode": mode,
            "source": source,
            "secret_scan": scan,
            "remediation": False,
            "owner_override_effect": "none",
        }

    def resolve(
        self,
        *,
        scope: str | None,
        handoff_id: str,
        change_id: str,
        actor: str,
    ) -> dict[str, Any]:
        state = self._load_state(scope)
        active = state.get("active_handoff")
        if state.get("status") != "blocked" or not isinstance(active, dict):
            raise SlapfaceError("No active Slapface handoff exists for this scope")
        if handoff_id != active.get("handoff_id"):
            raise SlapfaceError("handoff_id does not match the active Slapface blocker")
        report = next(
            (
                row
                for row in reversed(self.book.changes(limit=1000))
                if str(row.get("change_id")) == change_id
            ),
            None,
        )
        if report is None:
            raise SlapfaceError(f"No Book change report exists for change_id {change_id}")
        verification = report.get("verification") or {}
        verification_state = str(
            verification.get("state") or verification.get("status") or ""
        ).strip().lower()
        if verification_state not in _VERIFIED_STATES:
            raise SlapfaceError(
                "Slapface resolution requires a verified/passed/completed Book change report"
            )
        required_paths = {str(item) for item in active.get("required_paths") or []}
        changed_paths = {
            str(Path(item)).replace("\\", "/") for item in report.get("files_changed") or []
        }
        if required_paths and not required_paths.issubset(changed_paths):
            missing = sorted(required_paths.difference(changed_paths))
            raise SlapfaceError(
                "Verified change report does not cover required repair paths: "
                + ", ".join(missing)
            )
        state["status"] = "clear"
        state["active_handoff"] = None
        state.setdefault("history", []).append(
            {
                "event": "resolved",
                "handoff_id": handoff_id,
                "change_id": change_id,
                "actor": self.book._actor_id(actor),
                "at": _utcnow(),
            }
        )
        self._save_state(scope, state)
        return self.status(scope)


__all__ = ["Slapface", "SlapfaceError"]
