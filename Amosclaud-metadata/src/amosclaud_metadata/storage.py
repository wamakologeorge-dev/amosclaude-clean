"""Atomic JSON storage for append-only Amosclaud metadata records."""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
from typing import Any

from .models import MetadataEnvelope
from .validation import validate_envelope


class JsonMetadataStore:
    """Persist one immutable JSON document for every metadata record.

    Every path is resolved below a designated root. Writes go through a
    temporary file, are flushed to disk, and are atomically moved into place.
    Existing record IDs are never overwritten.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _record_path(self, envelope: MetadataEnvelope) -> Path:
        category = "".join(
            character
            for character in envelope.record_type.lower()
            if character.isalnum() or character in {"-", "_"}
        )
        if not category:
            raise ValueError(
                "record_type does not contain a safe path component"
            )

        directory = (self.root / category).resolve()
        if self.root not in directory.parents and directory != self.root:
            raise ValueError("metadata category escapes the configured root")

        directory.mkdir(parents=True, exist_ok=True)
        timestamp = envelope.created_at.replace(":", "-")
        return directory / f"{timestamp}_{envelope.record_id}.json"

    def append(self, envelope: MetadataEnvelope) -> Path:
        """Validate and atomically append an immutable metadata record."""
        validate_envelope(envelope)
        destination = self._record_path(envelope)

        with self._lock:
            if destination.exists():
                raise FileExistsError(
                    "metadata record already exists: "
                    f"{envelope.record_id}"
                )

            temporary = destination.with_suffix(destination.suffix + ".tmp")
            payload = json.dumps(
                envelope.to_dict(),
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            ) + "\n"

            try:
                with temporary.open("x", encoding="utf-8") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, destination)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise

        return destination

    def read(self, path: str | Path) -> dict[str, Any]:
        """Read one metadata file while enforcing the storage boundary."""
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        candidate = candidate.resolve()

        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("metadata read escapes the configured root")

        return json.loads(candidate.read_text(encoding="utf-8"))

    def list_records(self, record_type: str | None = None) -> list[Path]:
        """List metadata documents, optionally restricted by record type."""
        base = (
            self.root
            if record_type is None
            else (self.root / record_type).resolve()
        )
        if self.root not in base.parents and base != self.root:
            raise ValueError("metadata listing escapes the configured root")
        if not base.exists():
            return []
        return sorted(
            path for path in base.rglob("*.json") if path.is_file()
        )
