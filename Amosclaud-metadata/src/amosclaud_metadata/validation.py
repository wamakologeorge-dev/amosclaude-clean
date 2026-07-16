"""Validation rules for safe, truthful Amosclaud metadata."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .models import MetadataEnvelope


class MetadataValidationError(ValueError):
    """Raised when a metadata record violates the canonical contract."""


_SECRET_TERMS = {
    "password",
    "password_hash",
    "secret",
    "api_key",
    "token",
    "private_key",
    "authorization",
    "cookie",
    "session_id",
}


def _scan(value: Any, path: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _SECRET_TERMS or normalized.endswith("_secret") or normalized.endswith("_token"):
                raise MetadataValidationError(f"secret-like field is forbidden at {path}.{key}")
            _scan(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple, set)):
        for index, item in enumerate(value):
            _scan(item, f"{path}[{index}]")


def validate_envelope(envelope: MetadataEnvelope) -> None:
    if not envelope.record_type.strip():
        raise MetadataValidationError("record_type must not be empty")
    if not envelope.source.strip():
        raise MetadataValidationError("source must not be empty")
    if not isinstance(envelope.payload, dict) or not envelope.payload:
        raise MetadataValidationError("payload must be a non-empty object")
    if not envelope.schema_version.strip():
        raise MetadataValidationError("schema_version must not be empty")
    _scan(envelope.payload)
