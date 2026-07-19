from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Text, DateTime, Enum
from sqlalchemy.orm import declarative_base, relationship
import datetime
import enum

Base = declarative_base()

class PRStatus(enum.Enum):
    OPEN = "open"
    MERGED = "merged"
    CLOSED = "closed"

class CIStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"

class UserProfile(Base):
    __tablename__ = 'user_profiles'
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False)
    avatar_url = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    repositories = relationship("Repository", back_populates="owner")

class Repository(Base):
    __tablename__ = 'repositories'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey('user_profiles.id'), nullable=False)
    is_private = Column(Boolean, default=False, nullable=False)
    description = Column(Text, nullable=True)
    default_branch = Column(String(50), default="main", nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    owner = relationship("UserProfile", back_populates="repositories")
    pull_requests = relationship("PullRequest", back_populates="repository")

class PullRequest(Base):
    __tablename__ = 'pull_requests'
    id = Column(Integer, primary_key=True)
    repository_id = Column(Integer, ForeignKey('repositories.id'), nullable=False)
    creator_id = Column(Integer, ForeignKey('user_profiles.id'), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    source_branch = Column(String(100), nullable=False)
    target_branch = Column(String(100), nullable=False)
    status = Column(Enum(PRStatus), default=PRStatus.OPEN, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    repository = relationship("Repository", back_populates="pull_requests")
    comments = relationship("DiscussionComment", back_populates="pull_request")
    ci_pipelines = relationship("CIPipeline", back_populates="pull_request")

class DiscussionComment(Base):
    __tablename__ = 'discussion_comments'
    id = Column(Integer, primary_key=True)
    pull_request_id = Column(Integer, ForeignKey('pull_requests.id'), nullable=False)
    author_id = Column(Integer, ForeignKey('user_profiles.id'), nullable=False)
    line_number = Column(Integer, nullable=True) # Nullable if it is a general PR comment, populated if it's a code line review
    file_path = Column(String(255), nullable=True)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    pull_request = relationship("PullRequest", back_populates="comments")

class CIPipeline(Base):
    __tablename__ = 'ci_pipelines'
    id = Column(Integer, primary_key=True)
    pull_request_id = Column(Integer, ForeignKey('pull_requests.id'), nullable=True)
    repository_id = Column(Integer, ForeignKey('repositories.id'), nullable=False)
    commit_sha = Column(String(40), nullable=False)
    status = Column(Enum(CIStatus), default=CIStatus.PENDING, nullable=False)
    execution_logs = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    pull_request = relationship("PullRequest", back_populates="ci_pipelines")
