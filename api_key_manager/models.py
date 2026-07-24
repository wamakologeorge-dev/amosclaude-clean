"""Database models for the Amosclaud credential authority."""
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from .database import Base


class AgentUser(Base):
    __tablename__ = "agent_users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, onupdate=func.now())


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    key_prefix = Column(String, unique=True, index=True, nullable=False)
    hashed_key = Column(String, nullable=False)
    description = Column(String, nullable=True)
    # Comma-separated canonical scopes. Authorization code always parses and
    # validates individual values rather than using substring matching.
    scopes = Column(Text, nullable=False, default="tasks:read")
    created_by = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    expires_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)


class ApiKeyAuditEvent(Base):
    __tablename__ = "api_key_audit_events"

    id = Column(Integer, primary_key=True, index=True)
    key_id = Column(Integer, nullable=True, index=True)
    key_prefix = Column(String, nullable=True, index=True)
    event = Column(String, nullable=False, index=True)
    actor = Column(String, nullable=True)
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
