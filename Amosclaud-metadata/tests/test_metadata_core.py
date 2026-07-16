from __future__ import annotations

import json
from pathlib import Path

import pytest

from amosclaud_metadata import (
    AmosclaudMetadataService,
    JsonMetadataStore,
    MetadataEnvelope,
    MetadataValidationError,
    MissionRecord,
    VerificationState,
    validate_envelope,
)


def test_store_appends_verified_record_atomically(
    tmp_path: Path,
) -> None:
    store = JsonMetadataStore(tmp_path)
    service = AmosclaudMetadataService(store)
    mission = MissionRecord(
        mission_id="mission-1",
        objective="Build Amosclaud metadata",
        mode="build",
        status="completed",
        current_phase="report",
        completed_steps=(
            "understand",
            "inspect",
            "plan",
            "act",
            "verify",
            "report",
        ),
    )
    envelope = service.verified(
        "missions",
        mission,
        "pytest:test_store_appends_verified_record_atomically",
    )
    records = store.list_records("missions")
    assert len(records) == 1
    saved = json.loads(records[0].read_text(encoding="utf-8"))
    assert saved["record_id"] == envelope.record_id
    assert saved["verification"] == "verified"
    assert saved["payload"]["mission_id"] == "mission-1"
    assert list(tmp_path.rglob("*.tmp")) == []


def test_verified_record_requires_evidence(tmp_path: Path) -> None:
    service = AmosclaudMetadataService(JsonMetadataStore(tmp_path))
    with pytest.raises(ValueError, match="evidence"):
        service.verified("missions", {"mission_id": "mission-2"})


def test_sensitive_fields_are_rejected() -> None:
    envelope = MetadataEnvelope(
        record_type="runtime",
        payload={"api_key": "must-not-be-stored"},
    )
    with pytest.raises(MetadataValidationError, match="secret-like"):
        validate_envelope(envelope)


def test_nested_sensitive_fields_are_rejected() -> None:
    envelope = MetadataEnvelope(
        record_type="deployment",
        payload={
            "provider": "cloud",
            "configuration": {
                "runtime_access_token": "must-not-be-stored",
            },
        },
    )
    with pytest.raises(
        MetadataValidationError,
        match=r"configuration\.runtime_access_token",
    ):
        validate_envelope(envelope)


def test_empty_payload_is_rejected() -> None:
    envelope = MetadataEnvelope(record_type="health", payload={})
    with pytest.raises(MetadataValidationError, match="non-empty"):
        validate_envelope(envelope)


def test_record_is_append_only(tmp_path: Path) -> None:
    store = JsonMetadataStore(tmp_path)
    envelope = MetadataEnvelope(
        record_type="health",
        payload={"component": "model-router", "status": "healthy"},
        verification=VerificationState.VERIFIED,
        evidence=("health-check:200",),
    )
    store.append(envelope)
    with pytest.raises(FileExistsError):
        store.append(envelope)


def test_path_escape_is_rejected(tmp_path: Path) -> None:
    store = JsonMetadataStore(tmp_path)
    outside = tmp_path.parent / "outside.json"
    with pytest.raises(ValueError, match="escapes"):
        store.read(outside)
