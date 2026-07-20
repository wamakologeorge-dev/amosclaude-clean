"""Central application configuration for Amosclaud.

All application services should import ``settings`` from this module instead of
reading environment variables directly. Railway and local ``.env`` values use
the same names documented in ``.env.example``.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _runtime_secret_key() -> str:
    """Return a stable Railway-derived secret or a secure local fallback."""
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
    """Single source of truth for runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "Amosclaud AI"
    app_version: str = "1.0.0"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    allowed_hosts: List[str] = [
        "http://localhost",
        "http://localhost:8000",
        "http://www.amosclaud.com/",
    ]

    # Security
    secret_key: str = Field(default_factory=_runtime_secret_key)
    external_api_key: str = ""

    # Database and persistent storage
    database_url: str = "sqlite:///./data/amosclaud.db"
    auth_db_path: str = "./data/auth.db"
    repository_storage_path: str = "./data/repositories"
    storage_path: str = "./data/storage"

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = ""
    celery_result_backend: str = ""

    # Amosclaud public/customer API
    amosclaud_api_url: str = "http://www.amosclaud.com/"
    amosclaud_api_key: str = ""
    amosclaud_api_model: str = "amosclaud-agent"
    amosclaud_public_url: str = "http://www.amosclaud.com/"

    # Folder-owned model runtime
    amosclaud_model_home: str = "data/amosclaud-model"
    amosclaud_model_url: str = "http://127.0.0.1:8091"
    amosclaud_model: str = "amosclaud-folder-v1"
    amosclaud_model_token: str = ""
    amosclaud_model_timeout: int = 120

    # Optional external model providers
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"

    # Internal services
    auth_service_url: str = "http://localhost:8001"

    # Billing
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_full_monthly_price_id: str = ""
    stripe_full_annual_price_id: str = ""
    stripe_agent_starter_price_id: str = ""
    stripe_agent_builder_price_id: str = ""
    stripe_agent_studio_price_id: str = ""
    amosclaud_agent_credits_per_request: int = 1

    # Deployment
    deployment_retries: int = 3

    # Railway-managed metadata. These are optional and must not be manually
    # duplicated when Railway already injects them.
    railway_project_id: str = ""
    railway_service_id: str = ""
    railway_environment_id: str = ""
    railway_environment: str = ""
    railway_public_domain: str = ""

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in {"production", "prod"}

    @property
    def data_paths(self) -> tuple[Path, ...]:
        """Persistent paths that should exist before services start."""
        return (
            Path(self.auth_db_path).parent,
            Path(self.repository_storage_path),
            Path(self.storage_path),
            Path(self.amosclaud_model_home),
        )

    def ensure_runtime_directories(self) -> None:
        """Create configured persistent directories when possible."""
        for path in self.data_paths:
            path.mkdir(parents=True, exist_ok=True)

    def configured_integrations(self) -> dict[str, bool]:
        """Return integration availability without exposing secret values."""
        return {
            "database": bool(self.database_url),
            "redis": bool(self.redis_url),
            "amosclaud_api": bool(self.amosclaud_api_key),
            "amosclaud_model": bool(self.amosclaud_model_url),
            "openai": bool(self.openai_api_key),
            "stripe": bool(self.stripe_secret_key),
        }

    @field_validator("secret_key", mode="before")
    @classmethod
    def ensure_safe_secret(cls, value: object) -> str:
        candidate = str(value or "").strip()
        if len(candidate) >= 32 and candidate != "change-me-in-production":
            return candidate
        return _runtime_secret_key()

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def parse_allowed_hosts(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        raw = value.strip()
        if not raw:
            return [
                "http://localhost",
                "http://localhost:8000",
                "http://www.amosclaud.com/",
            ]
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
        return [item.strip() for item in raw.split(",") if item.strip()]

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "production", "prod"}:
                return False
            if normalized in {"debug", "development", "dev"}:
                return True
        return value

    @field_validator("celery_broker_url", mode="before")
    @classmethod
    def set_celery_broker(cls, value: str, info) -> str:
        return value or info.data.get("redis_url", "redis://localhost:6379/0")

    @field_validator("celery_result_backend", mode="before")
    @classmethod
    def set_celery_backend(cls, value: str, info) -> str:
        return value or info.data.get("redis_url", "redis://localhost:6379/0")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
