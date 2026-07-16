"""High-level service for recording verified Amosclaud engineering work."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from .models import MetadataEnvelope, VerificationState
from .storage import JsonMetadataStore


class AmosclaudMetadataService:
    """Create canonical envelopes through one storage boundary."""

    def __init__(
        self,
        store: JsonMetadataStore,
        *,
        source: str = "amosclaud-autonomous",
    ) -> None:
        self.store = store
        self.source = source

    def record(
        self,
        record_type: str,
        record: Any,
        *,
        verification: VerificationState = VerificationState.OBSERVED,
        evidence: tuple[str, ...] = (),
    ) -> MetadataEnvelope:
        """Normalize, wrap, validate, and persist one metadata record."""
        if is_dataclass(record) and not isinstance(record, type):
            payload = asdict(record)
        elif isinstance(record, dict):
            payload = dict(record)
        else:
            raise TypeError(
                "record must be a dataclass instance or dictionary"
            )

        envelope = MetadataEnvelope(
            record_type=record_type,
            payload=payload,
            source=self.source,
            verification=verification,
            evidence=tuple(item for item in evidence if item),
        )
        self.store.append(envelope)
        return envelope

    def verified(
        self,
        record_type: str,
        record: Any,
        *evidence: str,
    ) -> MetadataEnvelope:
        """Persist a verified record backed by at least one evidence reference."""
        if not evidence:
            raise ValueError(
                "verified metadata requires at least one evidence reference"
            )
        return self.record(
            record_type,
            record,
            verification=VerificationState.VERIFIED,
            evidence=tuple(evidence),
        )

    def failed(
        self,
        record_type: str,
        record: Any,
        *evidence: str,
    ) -> MetadataEnvelope:
        """Persist a failed result while preserving its evidence."""
        return self.record(
            record_type,
            record,
            verification=VerificationState.FAILED,
            evidence=tuple(evidence),
        )
