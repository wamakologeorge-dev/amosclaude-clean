"""Canonical metadata system for Amosclaud Autonomous and Amosclaud OS."""

from .models import (
    CommitRecord,
    DeploymentRecord,
    HealthRecord,
    MetadataEnvelope,
    MissionRecord,
    PipelineRecord,
    RepairRecord,
    RepositoryRecord,
    VerificationState,
)
from .service import AmosclaudMetadataService
from .storage import JsonMetadataStore
from .validation import MetadataValidationError, validate_envelope

__all__ = [
    "AmosclaudMetadataService",
    "CommitRecord",
    "DeploymentRecord",
    "HealthRecord",
    "JsonMetadataStore",
    "MetadataEnvelope",
    "MetadataValidationError",
    "MissionRecord",
    "PipelineRecord",
    "RepairRecord",
    "RepositoryRecord",
    "VerificationState",
    "validate_envelope",
]
