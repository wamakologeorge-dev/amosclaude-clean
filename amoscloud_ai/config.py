"""Application configuration using Pydantic Settings."""

from __future__ import annotations

import hashlib
import os
import secrets
from functools import lru_cache
from typing import List

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _runtime_secret_key() -> str:
    """Return a stable Railway-derived secret or a secure local fallback.

    Railway exposes stable project/service/environment identifiers. Hashing them
    gives the app a usable secret before a user supplies SECRET_KEY, preventing
    the server from crashing during startup and failing its health check.
    Production owners should still set a dedicated SECRET_KEY in Railway.
    """
    railway_parts = [
        os.getenv("RAILWAY_PROJECT_ID", ""),
        os.getenv("RAILWAY_SERVICE_ID", ""),
        os.getenv("RAILWAY_ENVIRONMENT_ID", ""),
    ]
    material = ":".join(part for part in railway_parts if part)
    if material:
        return hashlib.sha256(f"amosclaud:{material}".encode()).hexdigest()
    return secrets.token_urlsafe(48)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "Amosclaud AI"
    app_version: str = "1.0.0"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1

    # Database
    database_url: str = "sqlite:///./amoscloud.db"

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = ""
    celery_result_backend: str = ""

    # Security
    secret_key: str = Field(default_factory=_runtime_secret_key)
    allowed_hosts: List[str] = [
        "http://localhost",
        "http://localhost:8000",
        "https://amosclaud.com",
        "https://www.amosclaud.com",
    ]

    # Deployment
    deployment_retries: int = 3

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug(cls, v: object) -> object:
        if isinstance(v, str):
            normalized = v.strip().lower()
            if normalized in {"release", "production", "prod"}:
                return False
            if normalized in {"debug", "development", "dev"}:
                return True
        return v

    @field_validator("celery_broker_url", mode="before")
    @classmethod
    def set_celery_broker(cls, v: str, info) -> str:
        if not v:
            return info.data.get("redis_url", "redis://localhost:6379/0")
        return v

    @field_validator("celery_result_backend", mode="before")
    @classmethod
    def set_celery_backend(cls, v: str, info) -> str:
        if not v:
            return info.data.get("redis_url", "redis://localhost:6379/0")
        return v

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.environment.lower() in {"production", "prod", "release"}:
            if len(self.secret_key) < 32:
                raise ValueError("SECRET_KEY must contain at least 32 characters")
            if "*" in self.allowed_hosts:
                raise ValueError("ALLOWED_HOSTS must not contain '*' in production")
            if self.debug:
                raise ValueError("DEBUG must be disabled in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
