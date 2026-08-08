from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")
    RATE_LIMITING_ENABLE: bool = False
    RATE_LIMITING_FREQUENCY: str = "2/3seconds"
    PROXY_HOST: Optional[str] = None
    PROXY_PORT: Optional[str] = None
    PROXY_USERNAME: Optional[str] = None
    PROXY_PASSWORD: Optional[str] = None

    # Response caching
    CACHE_ENABLE: bool = True
    CACHE_MAX_ENTRIES: int = 2000
    CACHE_STALE_SECONDS: int = 604800  # 7 days: how long an expired entry stays servable when blocked
    CACHE_NEGATIVE_TTL: int = 300  # genuine 404s, so bad IDs are not re-scraped on every call
    CACHE_TTL_SHORT: int = 21600  # 6 hours
    CACHE_TTL_MEDIUM: int = 43200  # 12 hours
    CACHE_TTL_LONG: int = 86400  # 24 hours
    CACHE_TTL_ARCHIVE: int = 2592000  # 30 days, for immutable past-season data

    # Bot challenge (HTTP 202) circuit breaker
    BOT_BREAKER_ENABLE: bool = True
    BOT_BREAKER_THRESHOLD: int = 3
    BOT_BREAKER_COOLDOWN: int = 60

    @property
    def PROXY_URL(self) -> Optional[str]:
        if not self.PROXY_HOST or not self.PROXY_PORT:
            return None
        if self.PROXY_USERNAME and self.PROXY_PASSWORD:
            return f"http://{self.PROXY_USERNAME}:{self.PROXY_PASSWORD}@{self.PROXY_HOST}:{self.PROXY_PORT}"
        return f"http://{self.PROXY_HOST}:{self.PROXY_PORT}"


settings = Settings()
