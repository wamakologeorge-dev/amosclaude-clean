"""Request and response schemas for the Amosclaud credential authority."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

ALLOWED_SCOPES = {
    "tasks:read",
    "tasks:write",
    "repositories:read",
    "repositories:write",
    "ci:read",
    "ci:run",
    "pull-requests:create",
    "jobs:update",
    "deployments:read",
}


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


class AgentUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=128)
    password: str = Field(min_length=12, max_length=256)


class AgentUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    is_active: bool
    created_at: datetime


class ApiKeyCreate(BaseModel):
    description: Optional[str] = Field(default=None, max_length=512)
    expires_at: Optional[datetime] = None
    scopes: list[str] = Field(default_factory=lambda: ["tasks:read"], min_length=1, max_length=16)

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, scopes: list[str]) -> list[str]:
        normalized = sorted({scope.strip() for scope in scopes if scope.strip()})
        unknown = sorted(set(normalized) - ALLOWED_SCOPES)
        if unknown:
            raise ValueError(f"Unsupported API-key scopes: {', '.join(unknown)}")
        if not normalized:
            raise ValueError("At least one API-key scope is required")
        return normalized


class ApiKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key_prefix: str
    description: Optional[str]
    scopes: list[str]
    created_by: Optional[str]
    is_active: bool
    created_at: datetime
    expires_at: Optional[datetime]
    last_used_at: Optional[datetime]
    revoked_at: Optional[datetime]


class ApiKeyFullResponse(ApiKeyResponse):
    plain_key: str


class ApiKeyValidateRequest(BaseModel):
    api_key: str = Field(min_length=4, max_length=512)
    required_scopes: list[str] = Field(default_factory=list, max_length=16)

    @field_validator("required_scopes")
    @classmethod
    def validate_required_scopes(cls, scopes: list[str]) -> list[str]:
        normalized = sorted({scope.strip() for scope in scopes if scope.strip()})
        unknown = sorted(set(normalized) - ALLOWED_SCOPES)
        if unknown:
            raise ValueError(f"Unsupported required scopes: {', '.join(unknown)}")
        return normalized


class ApiKeyValidateResponse(BaseModel):
    is_valid: bool
    key_id: Optional[int] = None
    key_prefix: Optional[str] = None
    description: Optional[str] = None
    scopes: list[str] = Field(default_factory=list)
    is_active: Optional[bool] = None
    expires_at: Optional[datetime] = None
    message: str


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key_id: Optional[int]
    key_prefix: Optional[str]
    event: str
    actor: Optional[str]
    detail: Optional[str]
    created_at: datetime
