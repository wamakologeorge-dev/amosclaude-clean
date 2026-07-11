"""Application configuration using Pydantic Settings."""

from functools import lru_cache
from typing import List

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
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
    secret_key: str = "change-me-in-production"
    allowed_hosts: List[str] = ["http://localhost", "http://localhost:8000"]

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
            if self.secret_key == "change-me-in-production" or len(self.secret_key) < 32:
                raise ValueError("SECRET_KEY must be set to a strong value in production")
            if "*" in self.allowed_hosts:
                raise ValueError("ALLOWED_HOSTS must not contain '*' in production")
            if self.debug:
                raise ValueError("DEBUG must be disabled in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
