#!/usr/bin/env python3
"""Synchronize Amosclaud Storage memory and run the existing daily gateway."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import amosclaud_cron_gateway as gateway
from amoscloud_ai.repair_knowledge import VerifiedRepairMemory

_REMOTE_REQUEST = gateway._memory_request


def _catalog_path() -> Path | None:
    value = os.getenv("AMOSCLAUD_REPAIR_MEMORY_CATALOG", "").strip()
    return Path(value) if value else None


def _local_memory() -> VerifiedRepairMemory | None:
    path = _catalog_path()
    return VerifiedRepairMemory(path) if path is not None else None


def _write_catalog(catalog: dict[str, Any]) -> None:
    path = _catalog_path()
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(catalog, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _refresh_from_authority() -> bool:
    exported = _REMOTE_REQUEST("export", {})
    catalog = exported.get("catalog") if exported else None
    if not isinstance(catalog, dict):
        return False
    _write_catalog(catalog)
    return True


def _local_search(payload: dict[str, Any]) -> dict[str, Any] | None:
    memory = _local_memory()
    if memory is None:
        return None
    matches = memory.recall(
        str(payload.get("query") or ""),
        changed_files=[str(item) for item in payload.get("changed_files") or []],
        limit=int(payload.get("limit") or 4),
    )
    return {
        "matches": [item.technique_id for item in matches],
        "injection": memory.prompt_context(matches),
        "profile": memory.status(),
    }


def _local_learn(payload: dict[str, Any]) -> dict[str, Any] | None:
    memory = _local_memory()
    if memory is None:
        return None
    if payload.get("verified") is not True or str(
        payload.get("final_verdict") or ""
    ).upper() != "PASS":
        return None
    checks = payload.get("checks") or []
    if not checks or any(item.get("passed") is not True for item in checks):
        return None
    return memory.learn_verified(
        failure_evidence=str(payload.get("failure_evidence") or ""),
        changed_files=[str(item) for item in payload.get("changed_files") or []],
        verification_results=[
            {"name": str(item.get("name") or "verification"), "returncode": 0}
            for item in checks
        ],
        source=str(payload.get("source") or "amosclaud-daily-agent"),
        source_run_id=str(payload.get("source_run_id") or ""),
    )


def memory_request(path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    result = _REMOTE_REQUEST(path, payload)
    if result is not None:
        if path in {"learn", "failed"}:
            _refresh_from_authority()
        return result

    try:
        if path == "search":
            return _local_search(payload)
        if path == "learn":
            return _local_learn(payload)
        if path == "failed":
            memory = _local_memory()
            if memory is not None:
                return memory.record_failure(str(payload.get("reason") or "failed run"))
    except (OSError, ValueError, TypeError):
        return None
    return None


def main() -> int:
    _refresh_from_authority()
    gateway._memory_request = memory_request
    return gateway.main()


if __name__ == "__main__":
    raise SystemExit(main())
