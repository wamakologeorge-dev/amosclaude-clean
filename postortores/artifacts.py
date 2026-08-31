"""Content-addressed artifact storage for Amosclaud Postortores.

Artifacts are addressed by SHA-256 digest and stored outside relational rows so
build outputs, verification bundles, model assets, workspace snapshots, and
future machine-sync payloads can be deduplicated and verified independently.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


class ArtifactStore:
    """Filesystem-backed content-addressed storage with deterministic metadata."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.objects = self.root / "objects"
        self.metadata = self.root / "metadata"
        self.objects.mkdir(parents=True, exist_ok=True)
        self.metadata.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _object_path(self, digest: str) -> Path:
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("invalid sha256 digest")
        return self.objects / digest[:2] / digest[2:]

    def _metadata_path(self, digest: str) -> Path:
        return self.metadata / f"{digest}.json"

    def put(
        self,
        data: bytes,
        *,
        media_type: str = "application/octet-stream",
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        digest = self.digest(data)
        path = self._object_path(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            temp = path.with_suffix(".tmp")
            temp.write_bytes(data)
            os.replace(temp, path)
        meta = {
            "digest": digest,
            "size": len(data),
            "media_type": media_type,
            "labels": dict(sorted((labels or {}).items())),
        }
        self._metadata_path(digest).write_text(
            json.dumps(meta, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        return meta

    def get(self, digest: str) -> bytes:
        path = self._object_path(digest)
        data = path.read_bytes()
        if self.digest(data) != digest:
            raise IOError("artifact integrity verification failed")
        return data

    def describe(self, digest: str) -> dict[str, Any] | None:
        path = self._metadata_path(digest)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def verify(self, digest: str) -> bool:
        try:
            self.get(digest)
        except (FileNotFoundError, IOError, ValueError):
            return False
        return True
