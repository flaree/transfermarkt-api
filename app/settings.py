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

    @property
    def PROXY_URL(self) -> Optional[str]:
        if not self.PROXY_HOST or not self.PROXY_PORT:
            return None
        if self.PROXY_USERNAME and self.PROXY_PASSWORD:
            return f"http://{self.PROXY_USERNAME}:{self.PROXY_PASSWORD}@{self.PROXY_HOST}:{self.PROXY_PORT}"
        return f"http://{self.PROXY_HOST}:{self.PROXY_PORT}"


settings = Settings()
