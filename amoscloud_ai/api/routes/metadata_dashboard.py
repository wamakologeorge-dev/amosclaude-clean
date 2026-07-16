"""Metadata dashboard API for Amosclaud."""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from amoscloud_ai.api.routes.auth import get_user_from_session

router = APIRouter(prefix="/metadata", tags=["metadata-dashboard"])


def _metadata_root() -> Path:
    configured = os.getenv("AMOSCLAUD_METADATA_PATH", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.cwd() / "data" / "metadata").resolve()


def _require_user(request: Request):
    user = get_user_from_session(request.cookies.get("amos_session"))
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to view metadata")
    return user


def _record_type(record: dict[str, Any], path: Path) -> str:
    for key in ("type", "kind", "category", "record_type"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return path.parent.name or "unknown"


def _timestamp(record: dict[str, Any], path: Path) -> str:
    for key in ("updated_at", "created_at", "timestamp", "recorded_at"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def _safe_summary(record: dict[str, Any], path: Path) -> dict[str, Any]:
    return {
        "id": str(record.get("id") or record.get("record_id") or path.stem),
        "type": _record_type(record, path),
        "title": str(record.get("title") or record.get("name") or path.stem),
        "status": str(record.get("status") or "recorded"),
        "timestamp": _timestamp(record, path),
        "source": str(record.get("source") or record.get("agent") or "Amosclaud"),
        "path": str(path.relative_to(_metadata_root())),
    }


def _load_records(limit: int = 200) -> tuple[list[dict[str, Any]], list[str]]:
    root = _metadata_root()
    if not root.exists():
        return [], []

    records: list[dict[str, Any]] = []
    invalid: list[str] = []
    for path in sorted(root.rglob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        if len(records) >= limit:
            break
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                records.append(_safe_summary(raw, path))
            elif isinstance(raw, list):
                for index, item in enumerate(raw):
                    if isinstance(item, dict):
                        records.append(_safe_summary(item, path.with_name(f"{path.stem}-{index}.json")))
                        if len(records) >= limit:
                            break
        except (OSError, json.JSONDecodeError, ValueError):
            invalid.append(str(path.relative_to(root)))
    return records, invalid


@router.get("/summary")
def metadata_summary(request: Request) -> dict[str, Any]:
    user = _require_user(request)
    records, invalid = _load_records()
    types = Counter(item["type"] for item in records)
    statuses = Counter(item["status"] for item in records)
    return {
        "name": "Amosclaud Metadata Dashboard",
        "owner": {"id": int(user["id"]), "name": user["name"]},
        "storage": str(_metadata_root()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": {
            "records": len(records),
            "types": len(types),
            "invalid_files": len(invalid),
        },
        "types": dict(types.most_common()),
        "statuses": dict(statuses.most_common()),
        "recent": records[:25],
        "invalid": invalid[:25],
    }
