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
    """Persist metadata as one immutable JSON document per record.

    The store resolves every path below a designated root, writes through a temporary
    file, fsyncs the content, and atomically replaces the destination. Existing record
    IDs are never overwritten.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _record_path(self, envelope: MetadataEnvelope) -> Path:
        category = "".join(ch for ch in envelope.record_type.lower() if ch.isalnum() or ch in {"-", "_"})
        if not category:
            raise ValueError("record_type does not contain a safe path component")
        directory = (self.root / category).resolve()
        if self.root not in directory.parents and directory != self.root:
            raise ValueError("metadata category escapes the configured root")
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{envelope.created_at.replace(':', '-')}_{envelope.record_id}.json"

    def append(self, envelope: MetadataEnvelope) -> Path:
        validate_envelope(envelope)
        destination = self._record_path(envelope)
        with self._lock:
            if destination.exists():
                raise FileExistsError(f"metadata record already exists: {envelope.record_id}")
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            payload = json.dumps(envelope.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
            with temporary.open("x", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        return destination

    def read(self, path: str | Path) -> dict[str, Any]:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        candidate = candidate.resolve()
        if self.root not in candidate.parents:
            raise ValueError("metadata read escapes the configured root")
        return json.loads(candidate.read_text(encoding="utf-8"))

    def list_records(self, record_type: str | None = None) -> list[Path]:
        base = self.root if record_type is None else (self.root / record_type).resolve()
        if self.root not in base.parents and base != self.root:
            raise ValueError("metadata listing escapes the configured root")
        if not base.exists():
            return []
        return sorted(path for path in base.rglob("*.json") if path.is_file())
