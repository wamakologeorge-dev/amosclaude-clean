"""Atomic folder-based storage for Amosclaud Agent SDK sessions."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class SessionStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or os.getenv("AMOSCLAUD_SESSION_DIR", ".amosclaud/sessions")).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, session_id: str) -> Path:
        if not SESSION_ID.fullmatch(session_id):
            raise ValueError("invalid session identifier")
        return self.root / f"{session_id}.json"

    def load(self, session_id: str) -> dict[str, Any]:
        path = self.path(session_id)
        if not path.exists():
            raise FileNotFoundError(f"session not found: {session_id}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("invalid session document")
        return value

    def save(self, session_id: str, document: dict[str, Any]) -> Path:
        path = self.path(session_id)
        encoded = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        descriptor, temporary = tempfile.mkstemp(prefix=f".{session_id}-", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return path

    def list(self) -> list[str]:
        return sorted(path.stem for path in self.root.glob("*.json") if SESSION_ID.fullmatch(path.stem))
