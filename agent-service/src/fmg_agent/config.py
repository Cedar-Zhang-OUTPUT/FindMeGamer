"""Explicit, isolated service configuration; never load legacy .env files."""

from pathlib import Path
from typing import Literal
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
    twitch_client_id: str = ""
    twitch_client_secret: SecretStr = Field(default=SecretStr(""), repr=False)
    twitch_user_token: SecretStr = Field(default=SecretStr(""), repr=False)
    twitch_refresh_token: SecretStr = Field(default=SecretStr(""), repr=False)
    twitch_token_store: Path | None = None
    steam_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    gemini_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    gemini_model: str = ""
    broker_url: SecretStr = Field(
        default=SecretStr("redis://127.0.0.1:6379/0"), repr=False
    )
    email_retention_days: int = Field(default=30, ge=1, le=30)
    smtp_host: str = ""
    smtp_port: int = Field(default=465, ge=1, le=65535)
    smtp_encryption: Literal["tls", "starttls", "none"] = "tls"
    smtp_username: str = Field(default="", repr=False)
    smtp_password: SecretStr = Field(default=SecretStr(""), repr=False)
    smtp_from: str = ""
    smtp_allowed_recipients: list[str] = Field(default_factory=list)
    imap_host: str = ""
    imap_port: int = Field(default=993, ge=1, le=65535)
    imap_username: str = Field(default="", repr=False)
    imap_password: SecretStr = Field(default=SecretStr(""), repr=False)
    imap_folder: str = "INBOX"
    imap_poll_seconds: int = Field(default=60, ge=30, le=3600)
    imap_lookback_days: int = Field(default=30, ge=1, le=90)
    smtp_allow_insecure_loopback: bool = False
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
