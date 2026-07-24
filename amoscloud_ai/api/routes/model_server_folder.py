"""Model Server Folder System for staged, observable Amosclaud model activation.

This controller does not claim hardware ownership or load model weights by itself. It
creates a safe logical home for model engines, verifies the public Amosclaud API path,
and reports exactly how far the model service has progressed from 0% to 100%.
"""
from __future__ import annotations

import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai import model_network

router = APIRouter(prefix="/model-server-folder", tags=["model-server-folder"])

PUBLIC_HOME = "https://www.amosclaud.com"
DEFAULT_ROOT = Path(os.getenv("AMOSCLAUD_MODEL_SERVER_ROOT", "/data/amosclaud-model-server"))
STAGES = (
    (0, "folder-posted", "Model server folder definition exists."),
    (25, "folder-awake", "Folder structure and logical engines are initialized."),
    (70, "api-linked", "The model server is bound to the Amosclaud API identity."),
    (80, "station-ready", "At least one authenticated model station is online."),
    (100, "live", "The model network is ready to accept inference work."),
)


class WakeRequest(BaseModel):
    create_folders: bool = True
    engine_count: int = Field(default=100, ge=1, le=100)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _root() -> Path:
    return Path(os.getenv("AMOSCLAUD_MODEL_SERVER_ROOT", str(DEFAULT_ROOT))).resolve()


def _safe_create_layout(engine_count: int) -> list[str]:
    root = _root()
    created: list[str] = []
    for relative in (
        "chapter-1-discovery",
        "chapter-2-maintenance",
        "vacuum/inbox",
        "vacuum/processed",
        "runtime",
        "logs",
        "engines",
    ):
        path = root / relative
        path.mkdir(parents=True, exist_ok=True)
        created.append(str(path))
    for number in range(1, engine_count + 1):
        path = root / "engines" / f"engine-{number:03d}"
        path.mkdir(parents=True, exist_ok=True)
    marker = root / "runtime" / "model-server-home.txt"
    marker.write_text(PUBLIC_HOME + "\n", encoding="utf-8")
    created.append(str(marker))
    return created


def _hardware_identity() -> dict[str, Any]:
    """Report environment identity without modifying or claiming host hardware."""
    return {
        "hostname": socket.gethostname(),
        "location": os.getenv("RAILWAY_ENVIRONMENT_NAME") or os.getenv("AMOSCLAUD_HARDWARE_LOCATION") or "unknown",
        "provider": "railway" if os.getenv("RAILWAY_ENVIRONMENT") else "unknown",
        "human_hardware_untouched": True,
    }


def _progress(layout_ready: bool, network: dict[str, Any]) -> tuple[int, str, str]:
    if network.get("ready"):
        return STAGES[-1][0], STAGES[-1][1], STAGES[-1][2]
    if network.get("ready_stations", 0):
        return STAGES[3][0], STAGES[3][1], STAGES[3][2]
    if network.get("configured"):
        return STAGES[2][0], STAGES[2][1], STAGES[2][2]
    if layout_ready:
        return STAGES[1][0], STAGES[1][1], STAGES[1][2]
    return STAGES[0][0], STAGES[0][1], STAGES[0][2]


def status_payload() -> dict[str, Any]:
    root = _root()
    layout_ready = (root / "engines").is_dir() and (root / "runtime" / "model-server-home.txt").exists()
    network = model_network.network_status()
    percent, stage, detail = _progress(layout_ready, network)
    engines = 0
    if (root / "engines").is_dir():
        engines = sum(1 for item in (root / "engines").iterdir() if item.is_dir() and item.name.startswith("engine-"))
    return {
        "name": "Amosclaud Model Server Folder System",
        "public_home": PUBLIC_HOME,
        "api_path": "/api/v1/model-network",
        "root": str(root),
        "progress_percent": percent,
        "stage": stage,
        "detail": detail,
        "logical_engines": engines,
        "engine_target": 100,
        "network": network,
        "hardware": _hardware_identity(),
        "updated_at": _now(),
        "stages": [
            {"percent": value, "name": name, "meaning": meaning}
            for value, name, meaning in STAGES
        ],
    }


@router.get("/status")
def model_server_folder_status() -> dict[str, Any]:
    return status_payload()


@router.post("/wake")
def wake_model_server_folder(body: WakeRequest) -> dict[str, Any]:
    created: list[str] = []
    if body.create_folders:
        try:
            created = _safe_create_layout(body.engine_count)
        except OSError as exc:
            raise HTTPException(status_code=503, detail="Model server storage is not writable") from exc
    result = status_payload()
    result["wake_requested"] = True
    result["created_paths"] = created
    result["message"] = (
        "Model server folder is live and connected to Amosclaud.com."
        if result["progress_percent"] == 100
        else "Model server folder woke safely; remaining requirements are shown in status."
    )
    return result
