from functools import lru_cache
from ipaddress import ip_address, ip_network
from pathlib import Path
import re
from typing import Literal
import unicodedata
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.security import validate_workspace_key_hash

_s3_bucket = re.compile(
    r"^(?!xn--)(?!sthree-)(?!amzn-s3-demo-)[a-z0-9]" r"(?:[a-z0-9.-]{1,61}[a-z0-9])?$"
)
_aws_region = re.compile(r"^[a-z]{2}(?:-gov)?-[a-z]+-\d$")


def validate_external_base_url(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 2_048
        or "\\" in value
        or "%" in value
        or any(
            character.isspace() or unicodedata.category(character).startswith("C")
            for character in value
        )
    ):
        raise ValueError("External base URL is invalid.")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ValueError("External base URL is invalid.") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.startswith("//")
        or "//" in parsed.path
    ):
        raise ValueError("External base URL is invalid.")
    is_loopback = hostname.casefold() == "localhost"
    try:
        is_loopback = is_loopback or ip_address(hostname).is_loopback
    except ValueError:
        pass
    if parsed.scheme == "http" and not is_loopback:
        raise ValueError("External base URL must use HTTPS.")
    normalized_host = hostname.casefold()
    authority = f"[{normalized_host}]" if ":" in normalized_host else normalized_host
    if port is not None:
        authority = f"{authority}:{port}"
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, authority, path, "", ""))


class Settings(BaseSettings):
    database_url: str = (
        "postgresql+psycopg://postgres:postgres@localhost:5432/find_me_gamer"
    )
    redis_url: str = "redis://localhost:6379/0"
    workspace_access_key_hash: str
    workspace_rate_limit: int = Field(default=60, gt=0, le=10_000)
    workspace_rate_limit_window_seconds: int = Field(default=60, gt=0, le=3_600)
    redis_connect_timeout_seconds: float = Field(default=1.0, gt=0, le=10.0)
    redis_read_timeout_seconds: float = Field(default=1.0, gt=0, le=10.0)
    celery_broker_connect_timeout_seconds: float = Field(default=1.0, gt=0, le=10.0)
    celery_broker_socket_timeout_seconds: float = Field(default=2.0, gt=0, le=30.0)
    celery_broker_connection_max_retries: int = Field(default=3, ge=0, le=10)
    analysis_task_max_retries: int = Field(default=3, ge=0, le=10)
    analysis_retry_base_delay_seconds: int = Field(default=2, ge=1, le=300)
    analysis_retry_max_delay_seconds: int = Field(default=60, ge=1, le=3_600)
    outreach_task_max_retries: int = Field(default=3, ge=0, le=10)
    outreach_retry_base_delay_seconds: int = Field(default=2, ge=1, le=300)
    outreach_retry_max_delay_seconds: int = Field(default=60, ge=1, le=3_600)
    trusted_proxy_cidrs: tuple[str, ...] = ()
    master_key_file: Path = Path("/etc/find-me-gamer/master.key")
    steam_store_base_url: str = "https://store.steampowered.com/api"
    youtube_api_base_url: str = "https://www.googleapis.com/youtube/v3"
    deepseek_api_base_url: str = "https://api.deepseek.com"
    google_ai_api_base_url: str = (
        "https://generativelanguage.googleapis.com/v1beta/models"
    )
    external_base_url: str = "https://find-me-gamer.example.invalid"
    s3_region: str = "us-east-1"
    s3_bucket: str = "find-me-gamer-artifacts"
    s3_endpoint_url: str | None = None
    artifact_store: Literal["s3", "filesystem"] = "s3"
    artifact_directory: Path = Path("/var/lib/find-me-gamer/artifacts")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("workspace_access_key_hash")
    @classmethod
    def require_argon2id_hash(cls, value: str) -> str:
        return validate_workspace_key_hash(value)

    @model_validator(mode="after")
    def require_ordered_analysis_retry_delays(self) -> "Settings":
        if (
            self.analysis_retry_base_delay_seconds
            > self.analysis_retry_max_delay_seconds
        ):
            raise ValueError(
                "Analysis retry base delay must not exceed its maximum delay."
            )
        if (
            self.outreach_retry_base_delay_seconds
            > self.outreach_retry_max_delay_seconds
        ):
            raise ValueError(
                "Outreach retry base delay must not exceed its maximum delay."
            )
        return self

    @field_validator("trusted_proxy_cidrs")
    @classmethod
    def require_valid_proxy_networks(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            try:
                ip_network(value, strict=False)
            except ValueError:
                raise ValueError(f"Invalid trusted proxy CIDR: {value}") from None
        return values

    @field_validator(
        "steam_store_base_url",
        "youtube_api_base_url",
        "deepseek_api_base_url",
        "google_ai_api_base_url",
        "external_base_url",
        "s3_endpoint_url",
    )
    @classmethod
    def require_safe_external_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_external_base_url(value)

    @field_validator("s3_region")
    @classmethod
    def require_valid_s3_region(cls, value: str) -> str:
        if not _aws_region.fullmatch(value):
            raise ValueError("S3 region is invalid.")
        return value

    @field_validator("s3_bucket")
    @classmethod
    def require_valid_s3_bucket(cls, value: str) -> str:
        if (
            not _s3_bucket.fullmatch(value)
            or ".." in value
            or ".-" in value
            or "-." in value
        ):
            raise ValueError("S3 bucket is invalid.")
        try:
            ip_address(value)
        except ValueError:
            return value
        raise ValueError("S3 bucket is invalid.")

    @field_validator("artifact_directory")
    @classmethod
    def require_absolute_artifact_directory(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("Artifact directory must be absolute.")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
