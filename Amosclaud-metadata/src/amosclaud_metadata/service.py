"""High-level service used by Amosclaud Autonomous to record verified work."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from .models import MetadataEnvelope, VerificationState
from .storage import JsonMetadataStore


class AmosclaudMetadataService:
    """Create canonical envelopes and persist them through one storage boundary."""

    def __init__(self, store: JsonMetadataStore, *, source: str = "amosclaud-autonomous") -> None:
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
        if is_dataclass(record):
            payload = asdict(record)
        elif isinstance(record, dict):
            payload = dict(record)
        else:
            raise TypeError("record must be a dataclass instance or dictionary")
        envelope = MetadataEnvelope(
            record_type=record_type,
            payload=payload,
            source=self.source,
            verification=verification,
            evidence=tuple(item for item in evidence if item),
        )
        self.store.append(envelope)
        return envelope

    def verified(self, record_type: str, record: Any, *evidence: str) -> MetadataEnvelope:
        if not evidence:
            raise ValueError("verified metadata requires at least one evidence reference")
        return self.record(
            record_type,
            record,
            verification=VerificationState.VERIFIED,
            evidence=tuple(evidence),
        )

    def failed(self, record_type: str, record: Any, *evidence: str) -> MetadataEnvelope:
        return self.record(
            record_type,
            record,
            verification=VerificationState.FAILED,
            evidence=tuple(evidence),
        )
