"""Deterministic, checksum-verifiable Amosclaud bundle creation."""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class BundleError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class BundleResult:
    path: Path
    sha256: str
    size_bytes: int
    files: int


class BundleBuilder:
    def __init__(self, source: Path, *, excludes: tuple[str, ...] = ()) -> None:
        self.source = Path(source).resolve()
        self.excludes = {".git", "__pycache__", ".env", *excludes}
        if not self.source.is_dir():
            raise BundleError("bundle source must be a directory")

    def _files(self) -> list[Path]:
        files = []
        for path in self.source.rglob("*"):
            relative = path.relative_to(self.source)
            if path.is_file() and not any(part in self.excludes for part in relative.parts):
                files.append(path)
        return sorted(files, key=lambda path: path.relative_to(self.source).as_posix())

    def build(self, destination: Path, *, metadata: dict[str, Any] | None = None) -> BundleResult:
        destination = Path(destination).resolve()
        if destination.suffix != ".zip":
            raise BundleError("bundle destination must end in .zip")
        destination.parent.mkdir(parents=True, exist_ok=True)
        pending = destination.with_suffix(destination.suffix + ".tmp")
        files = self._files()
        manifest = {
            "schema_version": "1.0.0",
            "format": "amosclaud-bundle-v1",
            "metadata": metadata or {},
            "files": [
                {
                    "path": path.relative_to(self.source).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
                for path in files
            ],
        }
        try:
            with zipfile.ZipFile(pending, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path in files:
                    name = path.relative_to(self.source).as_posix()
                    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.external_attr = (path.stat().st_mode & 0xFFFF) << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, path.read_bytes())
                info = zipfile.ZipInfo("AMOSCLAUD_BUNDLE_MANIFEST.json", (1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            os.replace(pending, destination)
        finally:
            if pending.exists():
                pending.unlink()
        data = destination.read_bytes()
        return BundleResult(destination, hashlib.sha256(data).hexdigest(), len(data), len(files))


def verify_bundle(path: Path) -> dict[str, Any]:
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read("AMOSCLAUD_BUNDLE_MANIFEST.json"))
            for record in manifest["files"]:
                content = archive.read(record["path"])
                if len(content) != record["size"]:
                    raise BundleError(f"bundle size mismatch: {record['path']}")
                if hashlib.sha256(content).hexdigest() != record["sha256"]:
                    raise BundleError(f"bundle checksum mismatch: {record['path']}")
    except (KeyError, OSError, ValueError, zipfile.BadZipFile) as exc:
        if isinstance(exc, BundleError):
            raise
        raise BundleError("invalid Amosclaud bundle") from exc
    return {"valid": True, "files": len(manifest["files"]), "metadata": manifest["metadata"]}
