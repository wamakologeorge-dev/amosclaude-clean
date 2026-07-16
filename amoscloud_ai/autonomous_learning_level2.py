"""Compatibility boundary for the next governed Autonomous learning level.

Level-two behavior is intentionally disabled until its evidence and approval
contract is implemented. Keeping this module valid prevents optional future
work from breaking application startup, packaging, or strict lint checks.
"""

from __future__ import annotations


def status() -> dict[str, object]:
    """Return truthful availability without claiming an unfinished feature."""
    return {
        "available": False,
        "level": 2,
        "status": "not_implemented",
        "detail": "Governed level-two learning has not been enabled.",
    }
