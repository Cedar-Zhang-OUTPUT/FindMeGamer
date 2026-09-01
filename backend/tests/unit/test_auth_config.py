import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.security import hash_workspace_key
from app.main import create_app

VALID_WORKSPACE_HASH = hash_workspace_key("configuration-test-key")


class AlwaysAllow:
    def allow(self, workspace_digest: str, client_address: str) -> bool:
        return True


def test_settings_require_workspace_access_key_hash(monkeypatch) -> None:
    monkeypatch.delenv("WORKSPACE_ACCESS_KEY_HASH", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    "invalid_hash",
    [
        "",
        "not-an-argon2-hash",
        "$argon2i$v=19$m=65536,t=3,p=4$abc$def",
        "$argon2id$v=19$m=65536,t=3,p=4$abc$def",
        "$argon2id$v=19$m=0,t=0,p=0$YWJjZGVmZ2g$YWJjZGVmZ2hpamtsbW5vcA",
    ],
)
def test_settings_reject_non_argon2id_workspace_hash(invalid_hash: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, workspace_access_key_hash=invalid_hash)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("workspace_rate_limit", 0),
        ("workspace_rate_limit", 10_001),
        ("workspace_rate_limit_window_seconds", 0),
        ("workspace_rate_limit_window_seconds", 3_601),
        ("redis_connect_timeout_seconds", 0),
        ("redis_connect_timeout_seconds", 10.1),
        ("redis_read_timeout_seconds", 0),
        ("redis_read_timeout_seconds", 10.1),
    ],
)
def test_settings_reject_out_of_range_authentication_values(
    field: str, value: int | float
) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            workspace_access_key_hash=VALID_WORKSPACE_HASH,
            **{field: value},
        )


def test_settings_reject_invalid_trusted_proxy_cidr() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            workspace_access_key_hash=VALID_WORKSPACE_HASH,
            trusted_proxy_cidrs=("not-a-network",),
        )


def test_create_app_rejects_invalid_effective_workspace_hash() -> None:
    with pytest.raises(ValueError, match="Argon2id"):
        create_app(workspace_key_hash="", rate_limiter=AlwaysAllow())


def test_external_gateway_settings_have_canonical_server_only_defaults() -> None:
    settings = Settings(
        _env_file=None,
        workspace_access_key_hash=VALID_WORKSPACE_HASH,
    )

    assert settings.steam_store_base_url == "https://store.steampowered.com/api"
    assert settings.youtube_api_base_url == "https://www.googleapis.com/youtube/v3"
    assert settings.deepseek_api_base_url == "https://api.deepseek.com"
    assert settings.s3_region == "us-east-1"
    assert settings.s3_bucket == "find-me-gamer-artifacts"
    assert settings.s3_endpoint_url is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("steam_store_base_url", "http://store.steampowered.com/api"),
        ("youtube_api_base_url", "//www.googleapis.com/youtube/v3"),
        ("deepseek_api_base_url", "https://user@example.com"),
        ("deepseek_api_base_url", "https://api.deepseek.com?key=secret"),
        ("deepseek_api_base_url", "https://api.deepseek.com/#fragment"),
        ("s3_endpoint_url", "http://s3.example.com"),
        ("s3_bucket", "Bad_Bucket"),
        ("s3_region", ""),
    ],
)
def test_external_gateway_settings_reject_unsafe_values(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            workspace_access_key_hash=VALID_WORKSPACE_HASH,
            **{field: value},
        )


def test_external_gateway_settings_allow_loopback_http_and_strip_trailing_slash() -> (
    None
):
    settings = Settings(
        _env_file=None,
        workspace_access_key_hash=VALID_WORKSPACE_HASH,
        steam_store_base_url="http://127.0.0.1:18080/steam/",
        youtube_api_base_url="http://localhost:18081/youtube/v3/",
        deepseek_api_base_url="http://[::1]:18082/v1/",
        s3_endpoint_url="http://localhost:4566/",
    )

    assert settings.steam_store_base_url == "http://127.0.0.1:18080/steam"
    assert settings.youtube_api_base_url == "http://localhost:18081/youtube/v3"
    assert settings.deepseek_api_base_url == "http://[::1]:18082/v1"
    assert settings.s3_endpoint_url == "http://localhost:4566"
