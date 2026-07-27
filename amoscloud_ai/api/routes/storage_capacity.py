"""Compatibility entry point for the plugin-aware storage control plane.

The implementation is kept in ``storage_capacity_impl`` so the stacked plugin
branch can bind its optional feature-flag and provisioning dependencies without
forking the guarded storage implementation from the base branch.
"""

from __future__ import annotations

from typing import Any

from amoscloud_ai import feature_flags, storage_provisioning
from amoscloud_ai.api.routes import storage_capacity_impl as _impl

_HIGH_CAPACITY_THRESHOLD_GIB = _impl._HIGH_CAPACITY_THRESHOLD_GIB


def _high_capacity_decision(administrator: Any) -> dict[str, Any]:
    """Evaluate the administrator-scoped ``storage.high_capacity`` flag."""

    return feature_flags.evaluate(
        "storage.high_capacity",
        user_id=int(administrator["id"]),
    )


# Bind optional stacked-branch dependencies into the implementation module.
# Route functions retain that module as their global namespace.
_impl.storage_provisioning = storage_provisioning
_impl._high_capacity_decision = _high_capacity_decision

# Preserve the original route module's public and internal import contract.
for _name in dir(_impl):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_impl, _name)

del _name
