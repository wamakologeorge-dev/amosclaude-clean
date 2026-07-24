"""Shared SQLAlchemy models for the Amosclaud repository platform.

These records form one state layer for the API gateway, Autonomous Agent,
repository service, pull-request workflow, and CI/fixer verification service.
"""

from __future__ import annotations

import datetime
import enum

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class PRStatus(str, enum.Enum):
    OPEN = "open"
    MERGED = "merged"
    CLOSED = "closed"


class CIStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"


class AutonomousJobStatus(str, enum.Enum):
    QUEUED = "queued"
    INSPECTING = "inspecting"
    REPAIRING = "repairing"
    VERIFYING = "verifying"
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False)
    avatar_url = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    repositories = relationship("Repository", back_populates="owner", cascade="all, delete-orphan")
    pull_requests = relationship("PullRequest", back_populates="creator")
    comments = relationship("DiscussionComment", back_populates="author")
    autonomous_jobs = relationship("AutonomousJob", back_populates="requested_by")


class Repository(Base):
    __tablename__ = "repositories"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_repository_owner_name"),)

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    is_private = Column(Boolean, default=False, nullable=False)
    description = Column(Text, nullable=True)
    default_branch = Column(String(100), default="main", nullable=False)
    storage_path = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    owner = relationship("UserProfile", back_populates="repositories")
    pull_requests = relationship("PullRequest", back_populates="repository", cascade="all, delete-orphan")
    ci_pipelines = relationship("CIPipeline", back_populates="repository", cascade="all, delete-orphan")
    autonomous_jobs = relationship("AutonomousJob", back_populates="repository", cascade="all, delete-orphan")


class PullRequest(Base):
    __tablename__ = "pull_requests"

    id = Column(Integer, primary_key=True)
    repository_id = Column(Integer, ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False)
    creator_id = Column(Integer, ForeignKey("user_profiles.id"), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    source_branch = Column(String(100), nullable=False)
    target_branch = Column(String(100), nullable=False)
    status = Column(Enum(PRStatus), default=PRStatus.OPEN, nullable=False)
    merge_commit_sha = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    repository = relationship("Repository", back_populates="pull_requests")
    creator = relationship("UserProfile", back_populates="pull_requests")
    comments = relationship("DiscussionComment", back_populates="pull_request", cascade="all, delete-orphan")
    ci_pipelines = relationship("CIPipeline", back_populates="pull_request")
    autonomous_jobs = relationship("AutonomousJob", back_populates="pull_request")


class DiscussionComment(Base):
    __tablename__ = "discussion_comments"

    id = Column(Integer, primary_key=True)
    pull_request_id = Column(Integer, ForeignKey("pull_requests.id", ondelete="CASCADE"), nullable=False)
    author_id = Column(Integer, ForeignKey("user_profiles.id"), nullable=False)
    line_number = Column(Integer, nullable=True)
    file_path = Column(String(500), nullable=True)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    pull_request = relationship("PullRequest", back_populates="comments")
    author = relationship("UserProfile", back_populates="comments")


class CIPipeline(Base):
    __tablename__ = "ci_pipelines"

    id = Column(Integer, primary_key=True)
    pull_request_id = Column(Integer, ForeignKey("pull_requests.id", ondelete="SET NULL"), nullable=True)
    repository_id = Column(Integer, ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False)
    commit_sha = Column(String(64), nullable=False)
    status = Column(Enum(CIStatus), default=CIStatus.PENDING, nullable=False)
    execution_logs = Column(Text, nullable=True)
    verification_id = Column(String(100), nullable=True, unique=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    pull_request = relationship("PullRequest", back_populates="ci_pipelines")
    repository = relationship("Repository", back_populates="ci_pipelines")
    autonomous_jobs = relationship("AutonomousJob", back_populates="ci_pipeline")


class AutonomousJob(Base):
    __tablename__ = "autonomous_jobs"

    id = Column(Integer, primary_key=True)
    task_id = Column(String(100), unique=True, nullable=False, index=True)
    agent_type = Column(String(100), default="amosclaud-core", nullable=False)
    requested_by_id = Column(Integer, ForeignKey("user_profiles.id"), nullable=True)
    repository_id = Column(Integer, ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False)
    pull_request_id = Column(Integer, ForeignKey("pull_requests.id", ondelete="SET NULL"), nullable=True)
    ci_pipeline_id = Column(Integer, ForeignKey("ci_pipelines.id", ondelete="SET NULL"), nullable=True)
    objective = Column(Text, nullable=False)
    target_file = Column(String(500), nullable=True)
    error_context = Column(Text, nullable=True)
    status = Column(Enum(AutonomousJobStatus), default=AutonomousJobStatus.QUEUED, nullable=False)
    result_summary = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    requested_by = relationship("UserProfile", back_populates="autonomous_jobs")
    repository = relationship("Repository", back_populates="autonomous_jobs")
    pull_request = relationship("PullRequest", back_populates="autonomous_jobs")
    ci_pipeline = relationship("CIPipeline", back_populates="autonomous_jobs")
