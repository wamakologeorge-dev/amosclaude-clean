"""The governed Amosclaud executor product.

The package is intentionally small at its public boundary: callers provide an
authorized repository target, create a read-only plan, and execute that plan
only after an explicit confirmation.  All repository writes flow through the
existing bounded coding runtime.
"""

from .service import (
    ExecutionResult,
    ExecutorService,
    GatewayCodingModel,
    MemoryPlanStore,
    PlanStore,
    RepositoryTarget,
    SQLitePlanStore,
)

__all__ = [
    "ExecutionResult",
    "ExecutorService",
    "GatewayCodingModel",
    "MemoryPlanStore",
    "PlanStore",
    "RepositoryTarget",
    "SQLitePlanStore",
]
