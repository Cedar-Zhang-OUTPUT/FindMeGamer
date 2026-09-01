from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/find_me_gamer"
    redis_url: str = "redis://localhost:6379/0"
    workspace_access_key_hash: str = ""
    workspace_rate_limit: int = 60
    workspace_rate_limit_window_seconds: int = 60

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
