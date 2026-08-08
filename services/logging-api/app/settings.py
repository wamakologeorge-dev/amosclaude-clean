from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "amosclaud-logging-api"
    redis_url: str = "redis://redis:6379/0"
    redis_stream: str = "amosclaud:logs"
    redis_live_channel_prefix: str = "amosclaud:logs:live"
    api_keys: str = "local-dev-key:local"
    admin_api_key: str = ""
    max_batch_size: int = 500
    max_event_bytes: int = 262_144
    stream_maxlen: int = 1_000_000

    model_config = SettingsConfigDict(
        env_prefix="AMOSCLAUD_LOGGING_", env_file=".env", extra="ignore"
    )

    def tenant_keys(self) -> dict[str, str]:
        pairs: dict[str, str] = {}
        for item in self.api_keys.split(","):
            key, separator, tenant = item.strip().partition(":")
            if separator and key and tenant:
                pairs[key] = tenant
        return pairs


@lru_cache
def get_settings() -> Settings:
    return Settings()
