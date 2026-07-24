"""Build, index, verify, and safely install Amosclaud Y bundles."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import threading
import uuid
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from Amosclaud.lib.bundles import BundleBuilder, BundleError, verify_bundle

_BUNDLE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")
_MAX_FILES = 100_000
_MAX_EXTRACTED_BYTES = 8 * 1024**3


class YBundleErrorCB(ValueError):
    """Raised when a managed Y bundle violates integrity or safety rules."""


@dataclass(frozen=True, slots=True)
class YBundleRecordCB:
    schema_version: str
    bundle_id: str
    version: str
    archive: str
    archive_sha256: str
    size_bytes: int
    files: int
    created_at: str
    receipt_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class YBundleSystemCB:
    """Persistent folder-first registry for deterministic Amosclaud bundles."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.archives = self.root / "archives"
        self.receipts = self.root / "receipts"
        self.installations = self.root / "installations"
        self.index_path = self.root / "index.json"
        self._lock = threading.RLock()
        for path in (self.archives, self.receipts, self.installations):
            path.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            self._write_index({"schema": "amosclaud.y.bundle.system.cb/v1", "bundles": {}})

    def _read_index(self) -> dict[str, Any]:
        try:
            index = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise YBundleErrorCB("Y bundle index is unreadable") from exc
        if index.get("schema") != "amosclaud.y.bundle.system.cb/v1":
            raise YBundleErrorCB("Y bundle index schema is invalid")
        if not isinstance(index.get("bundles"), dict):
            raise YBundleErrorCB("Y bundle index records are invalid")
        return index

    def _write_index(self, index: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        pending = self.root / f".index-{uuid.uuid4().hex}.tmp"
        try:
            pending.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            os.replace(pending, self.index_path)
        finally:
            if pending.exists():
                pending.unlink()

    @staticmethod
    def _identifier(name: str, version: str) -> str:
        candidate = f"{name.strip().lower()}-{version.strip().lower()}"
        if not _BUNDLE_ID.fullmatch(candidate):
            raise YBundleErrorCB("bundle name and version produce an invalid identifier")
        return candidate

    @staticmethod
    def _receipt(unsigned: dict[str, Any]) -> dict[str, Any]:
        canonical = json.dumps(unsigned, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return {**unsigned, "receipt_sha256": hashlib.sha256(canonical).hexdigest()}

    def build(
        self,
        source: Path,
        *,
        name: str,
        version: str,
        metadata: dict[str, Any] | None = None,
    ) -> YBundleRecordCB:
        bundle_id = self._identifier(name, version)
        destination = self.archives / f"{bundle_id}.zip"
        with self._lock:
            index = self._read_index()
            if bundle_id in index["bundles"] or destination.exists():
                raise YBundleErrorCB(f"bundle already exists: {bundle_id}")
            try:
                result = BundleBuilder(Path(source)).build(
                    destination,
                    metadata={
                        "name": name.strip(),
                        "version": version.strip(),
                        "system": "Amosclaud.y.bundle.system.cb",
                        **(metadata or {}),
                    },
                )
            except BundleError as exc:
                raise YBundleErrorCB(str(exc)) from exc
            unsigned = {
                "schema_version": "1.0.0",
                "bundle_id": bundle_id,
                "version": version.strip(),
                "archive": destination.name,
                "archive_sha256": result.sha256,
                "size_bytes": result.size_bytes,
                "files": result.files,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            receipt = self._receipt(unsigned)
            receipt_path = self.receipts / f"{bundle_id}.cb.json"
            try:
                receipt_path.write_text(
                    json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                index["bundles"][bundle_id] = receipt
                self._write_index(index)
            except Exception:
                destination.unlink(missing_ok=True)
                receipt_path.unlink(missing_ok=True)
                raise
        return YBundleRecordCB(**receipt)

    def list(self) -> list[YBundleRecordCB]:
        with self._lock:
            records = self._read_index()["bundles"].values()
        ordered = sorted(records, key=lambda item: item["bundle_id"])
        return [YBundleRecordCB(**record) for record in ordered]

    def get(self, bundle_id: str) -> YBundleRecordCB:
        if not _BUNDLE_ID.fullmatch(bundle_id):
            raise YBundleErrorCB("invalid bundle identifier")
        with self._lock:
            record = self._read_index()["bundles"].get(bundle_id)
        if not record:
            raise YBundleErrorCB(f"bundle not found: {bundle_id}")
        return YBundleRecordCB(**record)

    def verify(self, bundle_id: str) -> dict[str, Any]:
        record = self.get(bundle_id)
        archive = self.archives / record.archive
        receipt = self.receipts / f"{bundle_id}.cb.json"
        if not archive.is_file() or not receipt.is_file():
            raise YBundleErrorCB("bundle archive or CB receipt is missing")
        archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
        if archive_sha != record.archive_sha256:
            raise YBundleErrorCB("bundle archive checksum mismatch")
        receipt_data = json.loads(receipt.read_text(encoding="utf-8"))
        supplied = receipt_data.pop("receipt_sha256", "")
        expected = self._receipt(receipt_data)["receipt_sha256"]
        if not supplied or supplied != expected or supplied != record.receipt_sha256:
            raise YBundleErrorCB("bundle CB receipt checksum mismatch")
        try:
            internal = verify_bundle(archive)
        except BundleError as exc:
            raise YBundleErrorCB(str(exc)) from exc
        return {
            "valid": True,
            "bundle_id": bundle_id,
            "archive_sha256": archive_sha,
            "receipt_sha256": supplied,
            "files": internal["files"],
            "metadata": internal["metadata"],
        }

    @staticmethod
    def _safe_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
        members = archive.infolist()
        if len(members) > _MAX_FILES:
            raise YBundleErrorCB("bundle contains too many files")
        total = 0
        for member in members:
            path = PurePosixPath(member.filename)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise YBundleErrorCB(f"unsafe bundle path: {member.filename}")
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise YBundleErrorCB(f"bundle symlink is not allowed: {member.filename}")
            total += member.file_size
            if total > _MAX_EXTRACTED_BYTES:
                raise YBundleErrorCB("bundle extracted size exceeds safety limit")
        return members

    def install(self, bundle_id: str, destination: Path | None = None) -> Path:
        self.verify(bundle_id)
        record = self.get(bundle_id)
        archive_path = self.archives / record.archive
        target = (
            Path(destination).expanduser().resolve()
            if destination
            else self.installations / bundle_id
        )
        if target.exists():
            raise YBundleErrorCB(f"installation target already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f".{bundle_id}-", dir=target.parent) as temporary:
            staging = Path(temporary) / "content"
            staging.mkdir()
            with zipfile.ZipFile(archive_path) as archive:
                members = self._safe_members(archive)
                for member in members:
                    output = staging.joinpath(*PurePosixPath(member.filename).parts)
                    if member.is_dir():
                        output.mkdir(parents=True, exist_ok=True)
                        continue
                    output.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, output.open("wb") as destination_stream:
                        shutil.copyfileobj(source, destination_stream, length=1024 * 1024)
            os.replace(staging, target)
        return target

    def status(self) -> dict[str, Any]:
        records = self.list()
        return {
            "status": "ready",
            "system": "Amosclaud.y.bundle.system.cb",
            "root": str(self.root),
            "bundles": len(records),
            "installed": sum(1 for item in self.installations.iterdir() if item.is_dir()),
        }
