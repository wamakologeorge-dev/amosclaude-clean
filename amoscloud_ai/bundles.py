"""Secure, reproducible Amosclaud bundle creation.

A bundle is a portable ZIP package containing selected project files plus a
machine-readable manifest. Bundles never include secrets, Git internals,
virtual environments, dependency caches, or runtime data.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

BUNDLE_FORMAT = "amosclaud.bundle.v1"
MAX_FILES = int(os.getenv("AMOSCLAUD_BUNDLE_MAX_FILES", "5000"))
MAX_SOURCE_BYTES = int(os.getenv("AMOSCLAUD_BUNDLE_MAX_SOURCE_BYTES", str(250 * 1024 * 1024)))
SKIP_PARTS = {
    ".git", ".github", ".amosclaud", ".venv", "venv", "node_modules",
    "__pycache__", ".pytest_cache", "dist", "build", "data", "secrets",
}
SKIP_NAMES = {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519"}


class BundleError(RuntimeError):
    """Raised when a bundle cannot be created safely."""


@dataclass(frozen=True)
class BundleFile:
    path: str
    size: int
    sha256: str


@dataclass
class BundleManifest:
    format: str
    bundle_id: str
    name: str
    version: str
    bundle_type: str
    created_at: str
    created_by: int
    source_root: str
    entrypoint: str | None = None
    description: str = ""
    metadata: dict = field(default_factory=dict)
    files: list[BundleFile] = field(default_factory=list)
    source_bytes: int = 0
    archive_sha256: str | None = None

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["files"] = [asdict(item) for item in self.files]
        return payload


@dataclass(frozen=True)
class BundleArtifact:
    manifest: BundleManifest
    archive_path: Path
    archive_size: int


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _safe_root(base_root: Path, source_path: str | None) -> Path:
    root = base_root.resolve()
    selected = (root / source_path).resolve() if source_path else root
    if not _inside(root, selected):
        raise BundleError("Bundle source must remain inside the Amosclaud workspace")
    if not selected.is_dir():
        raise BundleError("Bundle source folder does not exist")
    return selected


def _allowed(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in SKIP_PARTS for part in relative.parts):
        return False
    if path.name in SKIP_NAMES or path.name.startswith(".env."):
        return False
    if path.is_symlink():
        return False
    return True


def _files(root: Path) -> list[Path]:
    result: list[Path] = []
    total = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not _allowed(path, root):
            continue
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise BundleError(f"Unable to inspect {path.name}: {exc}") from exc
        total += size
        if len(result) + 1 > MAX_FILES:
            raise BundleError(f"Bundle exceeds the {MAX_FILES}-file safety limit")
        if total > MAX_SOURCE_BYTES:
            raise BundleError("Bundle exceeds the configured source-size safety limit")
        result.append(path)
    if not result:
        raise BundleError("No safe files were found for this bundle")
    return result


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_bundle(
    *,
    workspace_root: Path,
    output_root: Path,
    user_id: int,
    name: str,
    version: str,
    bundle_type: str,
    source_path: str | None = None,
    description: str = "",
    entrypoint: str | None = None,
    metadata: dict | None = None,
) -> BundleArtifact:
    source = _safe_root(workspace_root, source_path)
    selected = _files(source)
    bundle_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    manifest = BundleManifest(
        format=BUNDLE_FORMAT,
        bundle_id=bundle_id,
        name=name.strip(),
        version=version.strip(),
        bundle_type=bundle_type.strip(),
        created_at=now,
        created_by=user_id,
        source_root=source.relative_to(workspace_root.resolve()).as_posix() or ".",
        description=description.strip(),
        entrypoint=entrypoint.strip() if entrypoint else None,
        metadata=dict(metadata or {}),
    )

    for path in selected:
        relative = path.relative_to(source).as_posix()
        size = path.stat().st_size
        manifest.files.append(BundleFile(relative, size, _sha256_file(path)))
        manifest.source_bytes += size

    target_dir = output_root / str(user_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    archive_path = target_dir / f"{bundle_id}.amosbundle"
    fd, temporary_name = tempfile.mkstemp(prefix=f"{bundle_id}-", suffix=".tmp", dir=target_dir)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in selected:
                archive.write(path, arcname=f"payload/{path.relative_to(source).as_posix()}")
            archive.writestr("bundle.json", json.dumps(manifest.to_dict(), indent=2, sort_keys=True))
        os.replace(temporary, archive_path)
    finally:
        temporary.unlink(missing_ok=True)

    manifest.archive_sha256 = _sha256_file(archive_path)
    sidecar = archive_path.with_suffix(".json")
    sidecar.write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return BundleArtifact(manifest, archive_path, archive_path.stat().st_size)


def read_manifests(output_root: Path, user_id: int) -> Iterable[dict]:
    folder = output_root / str(user_id)
    if not folder.exists():
        return []
    manifests: list[dict] = []
    for path in sorted(folder.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            manifests.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return manifests
