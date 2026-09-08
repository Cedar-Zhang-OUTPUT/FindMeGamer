import pytest
from pydantic import ValidationError


def test_discovery_cursor_cannot_be_reused_for_another_query():
    from app.schemas.discovery import DiscoveryRequest, DiscoveryCursor

    original = DiscoveryRequest(platform="x", query="indie games")
    cursor = DiscoveryCursor(token="next-1", query_fingerprint=original.fingerprint())
    assert (
        DiscoveryRequest(platform="x", query="indie games", cursor=cursor).cursor
        == cursor
    )
    with pytest.raises(ValidationError):
        DiscoveryRequest(platform="x", query="different", cursor=cursor)


def test_discovery_limits_follow_provider_pages_and_do_not_claim_analysis():
    from app.schemas.discovery import DiscoveryRequest, platform_capabilities

    with pytest.raises(ValidationError):
        DiscoveryRequest(platform="youtube", query="game", page_size=51)
    with pytest.raises(ValidationError):
        DiscoveryRequest(platform="x", query="game", page_size=9)
    capabilities = {item.platform: item for item in platform_capabilities()}
    assert capabilities["x"].metadata_discovery_available
    assert capabilities["x"].analysis_available
    assert not capabilities["twitch"].metadata_discovery_available
    assert not capabilities["instagram"].metadata_discovery_available


def test_x_rejects_youtube_hints_instead_of_silently_ignoring_them():
    from app.schemas.discovery import DiscoveryRequest

    with pytest.raises(ValidationError):
        DiscoveryRequest(platform="x", query="game", region_hint="US")
