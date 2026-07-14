import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class CMoodConfig:
    # Base directories
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    WATCH_DIRECTORY: str = os.getenv("CMOOD_WATCH_DIR", str(BASE_DIR / "workspace"))
    CLONE_DIRECTORY: str = os.getenv("CMOOD_CLONE_DIR", str(BASE_DIR / "clones"))

    # Server configuration
    HOST: str = os.getenv("CMOOD_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("CMOOD_PORT", "3000"))

    # Security
    API_KEY: str = os.getenv("CMOOD_API_KEY", "cmood-super-secret-token-9988")

    # Worker configuration
    MAX_WORKERS: int = int(os.getenv("CMOOD_MAX_WORKERS", "4"))
    BUILD_TIMEOUT: int = int(os.getenv("CMOOD_BUILD_TIMEOUT", "300"))  # 5 minutes


settings = CMoodConfig()

# Ensure directories exist
Path(settings.WATCH_DIRECTORY).mkdir(parents=True, exist_ok=True)
Path(settings.CLONE_DIRECTORY).mkdir(parents=True, exist_ok=True)
