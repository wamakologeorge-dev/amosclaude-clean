"""Shared persistence models for the Amosclaud platform team.

The API gateway, Autonomous Agent, repository service, and CI service all use
this package as their common state contract.
"""

from .models import (
    AutonomousJob,
    AutonomousJobStatus,
    Base,
    CIPipeline,
    CIStatus,
    DiscussionComment,
    PRStatus,
    PullRequest,
    Repository,
    UserProfile,
)
from .session import create_database, get_session, session_scope

__all__ = [
    "AutonomousJob",
    "AutonomousJobStatus",
    "Base",
    "CIPipeline",
    "CIStatus",
    "DiscussionComment",
    "PRStatus",
    "PullRequest",
    "Repository",
    "UserProfile",
    "create_database",
    "get_session",
    "session_scope",
]
