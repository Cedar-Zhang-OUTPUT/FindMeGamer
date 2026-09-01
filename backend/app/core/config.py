from functools import lru_cache
from ipaddress import ip_network
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.security import validate_workspace_key_hash


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/find_me_gamer"
    redis_url: str = "redis://localhost:6379/0"
    workspace_access_key_hash: str
    workspace_rate_limit: int = Field(default=60, gt=0, le=10_000)
    workspace_rate_limit_window_seconds: int = Field(default=60, gt=0, le=3_600)
    redis_connect_timeout_seconds: float = Field(default=1.0, gt=0, le=10.0)
    redis_read_timeout_seconds: float = Field(default=1.0, gt=0, le=10.0)
    trusted_proxy_cidrs: tuple[str, ...] = ()
    master_key_file: Path = Path("/etc/find-me-gamer/master.key")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("workspace_access_key_hash")
    @classmethod
    def require_argon2id_hash(cls, value: str) -> str:
        return validate_workspace_key_hash(value)

    @field_validator("trusted_proxy_cidrs")
    @classmethod
    def require_valid_proxy_networks(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            try:
                ip_network(value, strict=False)
            except ValueError:
                raise ValueError(f"Invalid trusted proxy CIDR: {value}") from None
        return values


@lru_cache
def get_settings() -> Settings:
    return Settings()
