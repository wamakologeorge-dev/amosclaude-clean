"""CI/API bundle exposed as ``amosclaud.core.cb.db.py.ci.api.bundle``."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class CBApiBundle:
    name: str
    version: str = "1.0"
    database: str = "sqlite"
    language: str = "python"
    ci_provider: str = "generic"
    api_prefix: str = "/api/v1/cb"
    capabilities: tuple[str, ...] = (
        "component.register",
        "byte.encode",
        "byte.decode",
        "database.put",
        "database.get",
        "source.discover",
        "ci.verify",
        "api.describe",
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    def manifest(self) -> dict[str, Any]:
        data = asdict(self)
        data["created_at"] = datetime.now(timezone.utc).isoformat()
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
        data["digest"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return data

    def verify_manifest(self, manifest: dict[str, Any]) -> bool:
        supplied = str(manifest.get("digest") or "")
        unsigned = dict(manifest)
        unsigned.pop("digest", None)
        canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":"))
        return bool(supplied) and hashlib.sha256(canonical.encode("utf-8")).hexdigest() == supplied


def build_default_bundle(name: str = "amosclaud.core.cb.db.py.ci.api.bundle") -> CBApiBundle:
    return CBApiBundle(name=name)
