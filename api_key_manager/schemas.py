"""Request and response schemas for the API-key manager."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


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


class ApiKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key_prefix: str
    description: Optional[str]
    is_active: bool
    created_at: datetime
    expires_at: Optional[datetime]
    last_used_at: Optional[datetime]


class ApiKeyFullResponse(ApiKeyResponse):
    plain_key: str


class ApiKeyValidateRequest(BaseModel):
    api_key: str = Field(min_length=4, max_length=512)


class ApiKeyValidateResponse(BaseModel):
    is_valid: bool
    key_id: Optional[int] = None
    key_prefix: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    expires_at: Optional[datetime] = None
    message: str
