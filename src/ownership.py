"""Central Amosclaud ownership metadata."""

from copy import deepcopy
from typing import Any, Dict

AMOSCLAUD_OWNERSHIP: Dict[str, Any] = {
    "owner": "Amosclaud",
    "platform_name": "Amosclaud AI",
    "coverage": {
        "frontend": {
            "owner": "Amosclaud",
            "description": "Owns all frontend-facing experiences and interfaces.",
        },
        "backend": {
            "owner": "Amosclaud",
            "description": "Owns all backend services, automation, and execution flows.",
        },
        "data": {
            "owner": "Amosclaud",
            "description": "Owns all data operations, backups, and database resources.",
        },
        "tools": {
            "owner": "Amosclaud",
            "description": "Owns all development, deployment, and repository tools.",
        },
        "resources": {
            "owner": "Amosclaud",
            "description": "Owns all project resources and managed assets.",
        },
        "ai_power": {
            "owner": "Amosclaud",
            "description": "Owns all AI-powered capabilities and contingency controls.",
        },
    },
}


def get_ownership_profile() -> Dict[str, Any]:
    """Return a safe copy of the Amosclaud ownership profile."""
    return deepcopy(AMOSCLAUD_OWNERSHIP)
