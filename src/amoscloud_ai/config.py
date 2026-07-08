"""Application settings loaded from environment variables"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # Server
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Claude / Anthropic
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    claude_model: str = Field(default="claude-3-5-sonnet-20241022", alias="CLAUDE_MODEL")

    # Database
    database_url: str = Field(
        default="postgresql://localhost:5432/amoscloud_db",
        alias="DATABASE_URL",
    )

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # Deployment
    deployment_retries: int = Field(default=3, alias="DEPLOYMENT_RETRIES")

    # Upload limits
    max_upload_size_mb: int = Field(default=20, alias="MAX_UPLOAD_SIZE_MB")

    model_config = {"env_file": ".env", "populate_by_name": True}


settings = Settings()
