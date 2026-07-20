"""Verification policy shared by Amosclaud Autonomous and its tests.

Engineering work is complete only when a verification report explicitly passes
and includes a stable verification identifier. Conversational guidance does not
require build evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def verification_contract(
    *,
    engineering: bool,
    report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the canonical evidence state for an Amosclaud operation.

    The function is deliberately strict: missing, malformed, or failed reports
    never become verified. This prevents the fixer or agent from hiding a real
    failure behind a success message.
    """

    if not engineering:
        return {
            "required": False,
            "status": "not-applicable",
            "verified": True,
        }

    if not report:
        return {
            "required": True,
            "status": "pending",
            "verified": False,
        }

    status = str(report.get("status") or "pending").strip().lower()
    verification_id = str(report.get("verification_id") or "").strip()
    verified = status == "passed" and bool(verification_id)

    result: dict[str, Any] = {
        "required": True,
        "status": status,
        "verified": verified,
    }
    if verification_id:
        result["verification_id"] = verification_id
    return result
