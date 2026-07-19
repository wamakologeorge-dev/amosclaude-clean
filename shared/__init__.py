"""Shared contracts for the unified Amosclaud platform.

This package contains stable vocabulary and configuration contracts used by the
platform, Autonomous Agent, Amosclaud-Fixer, repository service, model runtime,
credential authority, metrics, SDK, and deployment tooling. Business logic must
remain in the owning service.
"""

from .runtime import ServiceEndpoint, ServiceName, platform_endpoints
from .statuses import ExecutionStatus
from .verification import VerificationEvidence

__all__ = [
    "ExecutionStatus",
    "ServiceEndpoint",
    "ServiceName",
    "VerificationEvidence",
    "platform_endpoints",
]
