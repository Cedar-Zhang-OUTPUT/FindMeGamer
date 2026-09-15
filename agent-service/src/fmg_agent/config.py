"""Explicit, isolated service configuration; never load legacy .env files."""

from pathlib import Path
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FMG_AGENT_", hide_input_in_errors=True
    )
    database_url: str = Field(repr=False)
    youtube_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    x_bearer_token: SecretStr = Field(default=SecretStr(""), repr=False)
    steam_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    catalog_dir: Path = Path(__file__).resolve().parents[3] / "api-catalog"

    @field_validator("database_url")
    @classmethod
    def isolated_database(cls, value: str) -> str:
        try:
            url = make_url(value)
        except Exception:
            raise ValueError("Invalid isolated database URL") from None
        if url.drivername == "sqlite":
            if not url.database or url.database == ":memory:":
                raise ValueError(
                    "Use a file-backed isolated SQLite database for local tests"
                )
            return value
        if url.drivername != "postgresql+psycopg" or url.database not in {
            "find_me_gamer_agent",
            "find_me_gamer_agent_test",
        }:
            raise ValueError("Use the isolated find_me_gamer_agent database")
        if set(url.query) - {"sslmode", "options"}:
            raise ValueError("Unsupported isolated database connection options")
        return value
