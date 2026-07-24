"""Mapping bundle registry and Amosclaud.bytes binary container."""
from __future__ import annotations

import hashlib
import json
import os
import struct
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAGIC = b"AMOSBYTES"
FORMAT_VERSION = 1
HEADER = struct.Struct(">9sBI32s")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_name(value: str) -> str:
    cleaned = "".join(ch for ch in value.strip() if ch.isalnum() or ch in "-_.")
    if not cleaned or cleaned.startswith("."):
        raise ValueError("bundle name must contain letters or numbers")
    return cleaned[:100]


@dataclass(frozen=True, slots=True)
class BundleRecord:
    name: str
    version: str
    filename: str
    byte_size: int
    mapping_count: int
    checksum: str
    created_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "filename": self.filename,
            "byte_size": self.byte_size,
            "mapping_count": self.mapping_count,
            "checksum": self.checksum,
            "created_at": self.created_at,
        }


class MappingBundleStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or os.getenv("AMOSCLAUD_BUNDLE_ROOT", ".amosclaud/mapping-bundles"))
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, *, name: str, version: str, mappings: dict[str, Any], metadata: dict[str, Any] | None = None) -> BundleRecord:
        safe_name = _safe_name(name)
        safe_version = _safe_name(version)
        created_at = _now()
        manifest = {
            "schema": "amosclaud.mapping-bundle/v1",
            "name": safe_name,
            "version": safe_version,
            "created_at": created_at,
            "metadata": metadata or {},
            "mappings": mappings,
        }
        raw = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        compressed = zlib.compress(raw, level=9)
        digest = hashlib.sha256(compressed).digest()
        payload = HEADER.pack(MAGIC, FORMAT_VERSION, len(compressed), digest) + compressed
        filename = f"{safe_name}-{safe_version}.Amosclaud.bytes"
        path = self.root / filename
        path.write_bytes(payload)
        return BundleRecord(
            name=safe_name,
            version=safe_version,
            filename=filename,
            byte_size=len(payload),
            mapping_count=len(mappings),
            checksum=digest.hex(),
            created_at=created_at,
        )

    def read(self, filename: str) -> dict[str, Any]:
        path = self.root / Path(filename).name
        data = path.read_bytes()
        if len(data) < HEADER.size:
            raise ValueError("bundle is truncated")
        magic, version, size, expected = HEADER.unpack(data[: HEADER.size])
        body = data[HEADER.size :]
        if magic != MAGIC or version != FORMAT_VERSION:
            raise ValueError("unsupported Amosclaud.bytes format")
        if len(body) != size or hashlib.sha256(body).digest() != expected:
            raise ValueError("bundle checksum verification failed")
        return json.loads(zlib.decompress(body).decode("utf-8"))

    def list(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("*.Amosclaud.bytes"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                manifest = self.read(path.name)
            except (OSError, ValueError, json.JSONDecodeError, zlib.error):
                continue
            records.append({
                "name": manifest["name"],
                "version": manifest["version"],
                "filename": path.name,
                "byte_size": path.stat().st_size,
                "mapping_count": len(manifest.get("mappings", {})),
                "created_at": manifest.get("created_at"),
                "metadata": manifest.get("metadata", {}),
            })
        return records

    def delete(self, filename: str) -> None:
        path = self.root / Path(filename).name
        if not path.exists():
            raise FileNotFoundError(filename)
        path.unlink()
