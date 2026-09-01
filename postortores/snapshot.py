"""Portable snapshot and restore helpers for Amosclaud Postortores."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class SnapshotManager:
    """Create verifiable portable snapshots of the bootstrap Postortores store."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def create(self, destination: str | Path) -> dict[str, Any]:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(str(self.database_path))
        target = sqlite3.connect(str(destination))
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        manifest = {
            "format": "amosclaud-postortores-snapshot-v1",
            "database": destination.name,
            "sha256": self._sha256(destination),
            "size": destination.stat().st_size,
            "created_at": time.time(),
        }
        destination.with_suffix(destination.suffix + ".manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        return manifest

    def verify(self, snapshot: str | Path) -> bool:
        snapshot = Path(snapshot)
        manifest_path = snapshot.with_suffix(snapshot.suffix + ".manifest.json")
        if not snapshot.exists() or not manifest_path.exists():
            return False
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(manifest, dict):
            return False
        return (
            manifest.get("format") == "amosclaud-postortores-snapshot-v1"
            and manifest.get("sha256") == self._sha256(snapshot)
            and manifest.get("size") == snapshot.stat().st_size
        )

    def restore(self, snapshot: str | Path, destination: str | Path) -> None:
        snapshot = Path(snapshot)
        destination = Path(destination)
        if not self.verify(snapshot):
            raise IOError("Postortores snapshot verification failed")
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(str(snapshot))
        target = sqlite3.connect(str(destination))
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
