# amos-api-gateway/config.py
import os
from dotenv import load_dotenv

load_dotenv() # Load environment variables from .env file

class Settings:
    PROJECT_NAME: str = "Amos API Gateway"
    PROJECT_VERSION: str = "1.0.0"

    # JWT Settings (should match your amosflow auth service)
    SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "super-secret-jwt-key")
    ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Backend Service URLs
    SERVICE_A_URL: str = os.getenv("SERVICE_A_URL", "http://localhost:8001")
    SERVICE_B_URL: str = os.getenv("SERVICE_B_URL", "http://localhost:8002")
    SERVICE_C_URL: str = os.getenv("SERVICE_C_URL", "http://localhost:8003")

    # Rate Limiting Settings
    RATE_LIMIT_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60")) # 60 requests per minute
    RATE_LIMIT_WINDOW_SECONDS: int = 60

settings = Settings()
