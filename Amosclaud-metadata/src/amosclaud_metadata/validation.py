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


def _is_sensitive_field(field_name: str) -> bool:
    """Return ``True`` if ``field_name`` looks like it carries a secret value.

    Checks against an explicit deny-list and common naming suffixes such as
    ``_secret``, ``_token``, ``_password``, and ``_api_key``.
    """
    normalized = field_name.strip().lower()
    return (
        normalized in _SECRET_TERMS
        or normalized.endswith("_secret")
        or normalized.endswith("_token")
        or normalized.endswith("_password")
        or normalized.endswith("_api_key")
    )


def _scan(value: Any, path: str = "payload") -> None:
    """Recursively walk ``value`` and raise on any secret-like dict key.

    Traverses mappings, lists, tuples, and sets. The ``path`` argument is
    used to build a human-readable dotted location string for error messages.

    Raises:
        MetadataValidationError: If any dict key matches :func:`_is_sensitive_field`.
    """
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _is_sensitive_field(str(key)):
                raise MetadataValidationError(
                    f"secret-like field is forbidden at {path}.{key}"
                )
            _scan(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple, set)):
        for index, item in enumerate(value):
            _scan(item, f"{path}[{index}]")


def validate_envelope(envelope: MetadataEnvelope) -> None:
    """Validate one metadata envelope before it reaches persistent storage.

    Checks that required string fields are non-blank, that ``payload`` is a
    non-empty dict, and that no key in the payload tree looks like a secret
    (passwords, tokens, API keys, etc.).

    Args:
        envelope: The :class:`~amosclaud_metadata.models.MetadataEnvelope` to validate.

    Raises:
        MetadataValidationError: On any validation failure, with a message
            describing the specific problem and location.
    """
    if not envelope.record_type.strip():
        raise MetadataValidationError("record_type must not be empty")
    if not envelope.source.strip():
        raise MetadataValidationError("source must not be empty")
    if not isinstance(envelope.payload, dict) or not envelope.payload:
        raise MetadataValidationError("payload must be a non-empty object")
    if not envelope.schema_version.strip():
        raise MetadataValidationError("schema_version must not be empty")
    _scan(envelope.payload)
