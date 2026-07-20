"""Canonical, secret-free metadata for Amosclaud model runtimes."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


class ModelMetadataError(ValueError):
    """Raised when the model metadata document is incomplete or malformed."""


_SOURCE_METADATA = (
    Path(__file__).resolve().parent.parent / "model-workspace" / "config" / "model_metadata.json"
)
_REQUIRED_TEXT = (
    "schema_version",
    "model_id",
    "display_name",
    "version",
    "owner",
    "model_family",
    "artifact_format",
)
_REQUIRED_LISTS = ("capabilities", "interfaces", "authentication")


def validate_model_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Validate the public model contract and return an isolated copy."""
    if not isinstance(metadata, dict):
        raise ModelMetadataError("model metadata must be a JSON object")
    for field in _REQUIRED_TEXT:
        if not isinstance(metadata.get(field), str) or not metadata[field].strip():
            raise ModelMetadataError(f"model metadata field '{field}' must be non-empty text")
    for field in _REQUIRED_LISTS:
        value = metadata.get(field)
        if not isinstance(value, list) or not value or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            raise ModelMetadataError(f"model metadata field '{field}' must be a non-empty list")
    generation = metadata.get("generation")
    if not isinstance(generation, dict) or not isinstance(generation.get("max_output_tokens"), int):
        raise ModelMetadataError("model metadata generation.max_output_tokens must be an integer")
    if generation["max_output_tokens"] < 1:
        raise ModelMetadataError("model metadata generation.max_output_tokens must be positive")
    forbidden = {"api_key", "token", "secret", "password"}

    def reject_credentials(value: Any, path: str = "") -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                location = f"{path}.{key}" if path else str(key)
                if str(key).lower() in forbidden:
                    raise ModelMetadataError(
                        f"model metadata must not contain credentials ({location})"
                    )
                reject_credentials(nested, location)
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                reject_credentials(nested, f"{path}[{index}]")

    reject_credentials(metadata)
    return deepcopy(metadata)


def load_model_metadata(model_root: Path | None = None) -> dict[str, Any]:
    """Load a workspace override when present, otherwise the packaged definition."""
    candidates = []
    if model_root is not None:
        candidates.append(Path(model_root) / "config" / "model_metadata.json")
    candidates.append(_SOURCE_METADATA)
    for path in candidates:
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ModelMetadataError(f"cannot load model metadata from {path}: {exc}") from exc
            return validate_model_metadata(payload)
    raise ModelMetadataError("model_metadata.json is missing")


def runtime_model_metadata(
    model_root: Path,
    *,
    runtime: str,
    ready: bool,
) -> dict[str, Any]:
    """Combine immutable model identity with truthful, non-persisted runtime state."""
    metadata = load_model_metadata(model_root)
    checkpoint = Path(model_root) / "checkpoints" / "current.json"
    metadata["runtime"] = {
        "engine": runtime,
        "ready": ready,
        "checkpoint_available": checkpoint.is_file(),
    }
    return metadata
