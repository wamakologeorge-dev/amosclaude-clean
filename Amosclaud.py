"""Portable Amosclaud Python bundle entry point.

This module intentionally has no network side effects. It combines the public CB
bundle with a small runtime manifest and can be imported or executed directly.

Examples::

    from Amosclaud import build_bundle
    bundle = build_bundle()
    assert bundle.verify()

    python Amosclaud.py describe
    python Amosclaud.py verify
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from amosclaud.core.cb.db.py.ci.api.bundle import CBApiBundle, build_default_bundle

BUNDLE_NAME = "Amosclaud.py"
BUNDLE_VERSION = "1.0"


@dataclass(frozen=True)
class AmosclaudPythonBundle:
    """Importable description of the Amosclaud Python distribution bundle."""

    name: str = BUNDLE_NAME
    version: str = BUNDLE_VERSION
    entry_point: str = "Amosclaud:main"
    api_bundle: CBApiBundle = field(default_factory=build_default_bundle)
    capabilities: tuple[str, ...] = (
        "bundle.describe",
        "bundle.verify",
        "component.register",
        "byte.encode",
        "byte.decode",
        "database.put",
        "database.get",
        "source.discover",
        "ci.verify",
        "api.describe",
    )

    def manifest(self) -> dict[str, Any]:
        """Return a self-verifying, JSON-safe manifest without secret values."""
        data: dict[str, Any] = {
            "name": self.name,
            "version": self.version,
            "entry_point": self.entry_point,
            "python": platform.python_version(),
            "platform": platform.system().lower() or "unknown",
            "capabilities": list(self.capabilities),
            "api_bundle": self.api_bundle.manifest(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
        data["digest"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return data

    @staticmethod
    def verify_manifest(manifest: dict[str, Any]) -> bool:
        """Verify a manifest created by :meth:`manifest`."""
        supplied = str(manifest.get("digest") or "")
        unsigned = dict(manifest)
        unsigned.pop("digest", None)
        canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":"))
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return bool(supplied) and supplied == expected

    def verify(self) -> bool:
        manifest = self.manifest()
        return self.verify_manifest(manifest) and self.api_bundle.verify_manifest(manifest["api_bundle"])

    def public_dict(self) -> dict[str, Any]:
        """Return stable bundle metadata suitable for APIs and dashboards."""
        return {
            "name": self.name,
            "version": self.version,
            "entry_point": self.entry_point,
            "capabilities": list(self.capabilities),
            "api_bundle": asdict(self.api_bundle),
            "verified": self.verify(),
        }


def build_bundle() -> AmosclaudPythonBundle:
    """Build the default ``Amosclaud.py`` bundle."""
    return AmosclaudPythonBundle()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="Amosclaud.py", description="Inspect and verify the Amosclaud Python bundle")
    parser.add_argument("command", choices=("describe", "manifest", "verify"), nargs="?", default="describe")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    bundle = build_bundle()
    if args.command == "verify":
        verified = bundle.verify()
        print(json.dumps({"bundle": bundle.name, "verified": verified}, sort_keys=True))
        return 0 if verified else 1
    payload = bundle.manifest() if args.command == "manifest" else bundle.public_dict()
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
