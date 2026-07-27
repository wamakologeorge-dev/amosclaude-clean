"""Deterministic security objectives and receipts for repair workflows."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


def evidence_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fixer_objective(failure_evidence: str) -> str:
    """Return a bounded objective without embedding untrusted log content."""
    return f"repair verified CI failure evidence sha256:{evidence_digest(failure_evidence)}"


def verification_receipt(report: Mapping[str, Any]) -> str:
    """Hash the security-relevant verified repair result."""
    material = {
        "status": report.get("status"),
        "provider": report.get("provider"),
        "model": report.get("model"),
        "changed_files": sorted(
            str(item) for item in (report.get("changed_files") or []) if item
        ),
        "security": report.get("security") or {},
    }
    serialized = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def publish_objective(report: Mapping[str, Any]) -> str:
    return f"publish verified repair receipt sha256:{verification_receipt(report)}"


def load_report(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("repair report must be a JSON object")
    return payload
