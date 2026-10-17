from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # DB URL/pool/JWT settings belong to Parts 2, 4 and 8; the API only needs this one.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ready_timeout_ms: int = 1000


@lru_cache
def get_settings() -> Settings:
    return Settings()
