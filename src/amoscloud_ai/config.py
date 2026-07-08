"""Configuration settings for Amoscloud AI"""

import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    """Application settings"""

    deployment_retries: int = int(os.getenv("DEPLOYMENT_RETRIES", "3"))
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///amoscloud.db")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"


settings = Settings()
