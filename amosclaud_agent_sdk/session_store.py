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
    """Atomic, folder-based persistence for :class:`~amosclaud_agent_sdk.sessions.AgentSession` documents.

    Each session is stored as a single ``<session_id>.json`` file under
    ``root``. Writes are atomic: data is flushed and fsync'd to a temp file
    then renamed over the target, so readers never see a partial write.

    The storage root defaults to ``.amosclaud/sessions`` relative to the
    current directory, or the value of the ``AMOSCLAUD_SESSION_DIR`` environment
    variable when set.
    """

    def __init__(self, root: str | Path | None = None) -> None:
        """
        Args:
            root: Absolute or relative path for session storage. Created
                automatically (including parents) if absent.
        """
        self.root = Path(root or os.getenv("AMOSCLAUD_SESSION_DIR", ".amosclaud/sessions")).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, session_id: str) -> Path:
        """Return the expected file path for ``session_id`` without touching the filesystem.

        Args:
            session_id: Must match ``[A-Za-z0-9][A-Za-z0-9._-]{0,127}``.

        Raises:
            ValueError: If ``session_id`` fails validation.
        """
        if not SESSION_ID.fullmatch(session_id):
            raise ValueError("invalid session identifier")
        return self.root / f"{session_id}.json"

    def load(self, session_id: str) -> dict[str, Any]:
        """Read and deserialize a session document.

        Args:
            session_id: Identifier of the session to load.

        Returns:
            The raw session dict (not yet parsed into an :class:`AgentSession`).

        Raises:
            ValueError: If ``session_id`` is invalid or the file content is not a dict.
            FileNotFoundError: If no file exists for ``session_id``.
        """
        path = self.path(session_id)
        if not path.exists():
            raise FileNotFoundError(f"session not found: {session_id}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("invalid session document")
        return value

    def save(self, session_id: str, document: dict[str, Any]) -> Path:
        """Atomically persist ``document`` as the session file for ``session_id``.

        The write sequence is: open temp file → write → flush → fsync → atomic rename.
        The temp file is always cleaned up, even on failure.

        Args:
            session_id: Target session identifier.
            document: JSON-serializable dict to persist.

        Returns:
            The resolved path of the written session file.
        """
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
        """Return sorted IDs of all valid session files under ``root``."""
        return sorted(path.stem for path in self.root.glob("*.json") if SESSION_ID.fullmatch(path.stem))
