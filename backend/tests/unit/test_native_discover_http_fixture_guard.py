import pytest


@pytest.mark.parametrize("url", [
    "postgresql+psycopg://postgres:postgres@postgres-test:5432/find_me_gamer_test",
    "postgresql+psycopg://postgres:postgres@production:5432/find_me_gamer_discover_http_acceptance",
    "postgresql+psycopg://postgres:postgres@postgres-test:5432/find_me_gamer_native_http_acceptance",
    "sqlite:///find_me_gamer_discover_http_acceptance",
])
def test_discover_fixture_rejects_other_databases_before_connecting(url):
    from tests.native_discover_http_fixture import validate_database

    with pytest.raises(ValueError, match="dedicated Discover acceptance"):
        validate_database(url)
