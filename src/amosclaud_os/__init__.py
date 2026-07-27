"""Amosclaud OS public interface.

Every platform entry point must resolve through the single AutonomousKernel.
"""

from typing import Any

from .kernel import AutonomousKernel, SystemIdentity, get_autonomous_kernel

_ORIGINAL_WRITE_DOCUMENT = AutonomousKernel.write_document


def _write_document_with_boolean_contract(
    self: AutonomousKernel,
    relative_path: str,
    content: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Keep the historical connector ``ok`` field alongside security metadata."""

    result = dict(
        _ORIGINAL_WRITE_DOCUMENT(
            self,
            relative_path,
            content,
            **kwargs,
        )
    )
    result.setdefault(
        "ok",
        not bool(result.get("error"))
        and str(result.get("status") or "").lower() not in {"blocked", "failed"},
    )
    return result


AutonomousKernel.write_document = _write_document_with_boolean_contract

__all__ = ["AutonomousKernel", "SystemIdentity", "get_autonomous_kernel"]
