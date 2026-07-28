"""Signed, folder-based plugin packages for the local Amosclaud node."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .crypto_identity import IdentityError, _unb64, signing_key_id, verify_signature


class PluginPackageError(RuntimeError):
    """Raised when a plugin package fails integrity, trust, or path validation."""


_NAME = re.compile(r"^[a-z][a-z0-9_.-]{1,79}$")
_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}(?:[-+][A-Za-z0-9.-]+)?$")
_ENTRYPOINT = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED = {"amosclaud-plugin.json", "amosclaud-plugin.sig"}
_PROTECTED_PARTS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    "amosclaud_vault",
    ".venv",
    "venv",
    "node_modules",
}


@dataclass(frozen=True)
class VerifiedPlugin:
    name: str
    version: str
    publisher: str
    entrypoint: str
    package_digest: str
    install_path: str | None = None


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _safe_relative_path(value: str) -> Path:
    path = Path(str(value or ""))
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise PluginPackageError("Plugin file path is invalid")
    if any(part in _PROTECTED_PARTS for part in path.parts):
        raise PluginPackageError("Plugin package contains a protected path")
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class PluginTrustStore:
    """Local allowlist of publisher IDs to Ed25519 public keys."""

    def __init__(self, publishers: Mapping[str, str] | None = None) -> None:
        self._publishers = dict(publishers or {})

    def trust(self, publisher_id: str, signing_public_key: str) -> None:
        try:
            raw = _unb64(signing_public_key)
        except IdentityError as exc:
            raise PluginPackageError("Publisher key is invalid") from exc
        derived = signing_key_id(raw)
        if derived != publisher_id:
            raise PluginPackageError("Publisher ID does not match the signing key")
        self._publishers[publisher_id] = signing_public_key

    def public_key(self, publisher_id: str) -> str:
        try:
            return self._publishers[publisher_id]
        except KeyError as exc:
            raise PluginPackageError("Plugin publisher is not trusted locally") from exc


class FolderPluginRegistry:
    """Verify and install a signed package from a local folder.

    Installation copies only manifest-declared regular files. It never imports or
    executes the package. Activation remains a separate, explicit operation.
    """

    def __init__(self, install_root: Path, trust_store: PluginTrustStore) -> None:
        self.install_root = Path(install_root).expanduser().resolve()
        self.trust_store = trust_store

    def verify(self, package_dir: Path) -> VerifiedPlugin:
        root = Path(package_dir).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise PluginPackageError("Plugin package must be a directory")
        manifest_path = root / "amosclaud-plugin.json"
        signature_path = root / "amosclaud-plugin.sig"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            signature = signature_path.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PluginPackageError(
                "Plugin manifest or signature is unreadable"
            ) from exc
        if not isinstance(manifest, dict):
            raise PluginPackageError("Plugin manifest must be an object")
        required = {
            "schema",
            "name",
            "version",
            "publisher",
            "entrypoint",
            "files",
        }
        if not required.issubset(manifest):
            raise PluginPackageError("Plugin manifest is incomplete")
        if manifest["schema"] != "amosclaud.plugin.v1":
            raise PluginPackageError("Unsupported plugin manifest schema")
        name = str(manifest["name"])
        version = str(manifest["version"])
        publisher = str(manifest["publisher"])
        entrypoint = str(manifest["entrypoint"])
        if not _NAME.fullmatch(name):
            raise PluginPackageError("Plugin name is invalid")
        if not _VERSION.fullmatch(version):
            raise PluginPackageError("Plugin version is invalid")
        if not _ENTRYPOINT.fullmatch(entrypoint):
            raise PluginPackageError("Plugin entrypoint is invalid")
        files = manifest["files"]
        if not isinstance(files, dict) or not files:
            raise PluginPackageError("Plugin manifest must declare package files")
        declared: set[Path] = set()
        for raw_path, expected_digest in files.items():
            relative = _safe_relative_path(str(raw_path))
            if relative.name in _RESERVED:
                raise PluginPackageError(
                    "Reserved metadata files cannot be plugin payload"
                )
            source = root / relative
            if source.is_symlink() or not source.is_file():
                raise PluginPackageError(
                    "Plugin payload must contain regular files only"
                )
            if _sha256_file(source) != str(expected_digest):
                raise PluginPackageError(f"Plugin file digest mismatch: {relative}")
            declared.add(relative)

        actual: set[Path] = set()
        for source in root.rglob("*"):
            if source.is_symlink():
                raise PluginPackageError("Plugin packages cannot contain symlinks")
            if source.is_file():
                relative = source.relative_to(root)
                if relative.name not in _RESERVED:
                    actual.add(relative)
        if actual != declared:
            raise PluginPackageError(
                "Plugin package contains undeclared or missing files"
            )

        public_key = self.trust_store.public_key(publisher)
        try:
            verify_signature(public_key, _canonical_json(manifest), signature)
        except IdentityError as exc:
            raise PluginPackageError("Plugin signature verification failed") from exc
        digest = hashlib.sha256(_canonical_json(manifest)).hexdigest()
        return VerifiedPlugin(
            name=name,
            version=version,
            publisher=publisher,
            entrypoint=entrypoint,
            package_digest=digest,
        )

    def install(self, package_dir: Path) -> VerifiedPlugin:
        verified = self.verify(package_dir)
        source_root = Path(package_dir).expanduser().resolve(strict=True)
        destination = self.install_root / verified.name / verified.version
        if destination.exists():
            raise PluginPackageError("This plugin version is already installed")
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = Path(
            tempfile.mkdtemp(
                prefix=f".{verified.name}-{verified.version}-",
                dir=destination.parent,
            )
        )
        try:
            manifest = json.loads(
                (source_root / "amosclaud-plugin.json").read_text(encoding="utf-8")
            )
            for raw_path in manifest["files"]:
                relative = _safe_relative_path(str(raw_path))
                target = temporary / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_root / relative, target)
            shutil.copyfile(
                source_root / "amosclaud-plugin.json",
                temporary / "amosclaud-plugin.json",
            )
            shutil.copyfile(
                source_root / "amosclaud-plugin.sig",
                temporary / "amosclaud-plugin.sig",
            )
            try:
                for path in temporary.rglob("*"):
                    if path.is_file():
                        os.chmod(path, 0o600)
                os.chmod(temporary, 0o700)
            except OSError:
                pass
            temporary.replace(destination)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return VerifiedPlugin(
            **{
                **verified.__dict__,
                "install_path": str(destination),
            }
        )


def create_manifest(
    *,
    package_dir: Path,
    name: str,
    version: str,
    publisher: str,
    entrypoint: str,
) -> dict[str, Any]:
    """Build a deterministic manifest for a folder before the publisher signs it."""

    root = Path(package_dir).expanduser().resolve(strict=True)
    files: dict[str, str] = {}
    for source in sorted(root.rglob("*")):
        if source.is_symlink():
            raise PluginPackageError("Plugin packages cannot contain symlinks")
        if not source.is_file() or source.name in _RESERVED:
            continue
        relative = _safe_relative_path(str(source.relative_to(root)))
        files[relative.as_posix()] = _sha256_file(source)
    manifest = {
        "schema": "amosclaud.plugin.v1",
        "name": name,
        "version": version,
        "publisher": publisher,
        "entrypoint": entrypoint,
        "files": files,
    }
    if not _NAME.fullmatch(name) or not _VERSION.fullmatch(version):
        raise PluginPackageError("Plugin name or version is invalid")
    if not _ENTRYPOINT.fullmatch(entrypoint):
        raise PluginPackageError("Plugin entrypoint is invalid")
    if not files:
        raise PluginPackageError("Plugin package contains no payload files")
    return manifest


def canonical_manifest_bytes(manifest: Mapping[str, Any]) -> bytes:
    return _canonical_json(manifest)
