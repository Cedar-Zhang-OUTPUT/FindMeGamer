import pytest
from pydantic import ValidationError


def test_query_requires_unique_sources_and_rejects_client_cursor():
    from app.schemas.activity import QueryCreate

    provider = {"platform": "x", "query": "indie"}
    with pytest.raises(ValidationError):
        QueryCreate(providers=[provider, provider])
    with pytest.raises(ValidationError):
        QueryCreate(providers=[])
    from app.schemas.discovery import DiscoveryRequest

    request = DiscoveryRequest(platform="x", query="indie")
    with pytest.raises(ValidationError):
        QueryCreate(
            providers=[
                provider
                | {
                    "cursor": {
                        "token": "next",
                        "query_fingerprint": request.fingerprint(),
                    }
                }
            ]
        )


def test_follower_filter_rejects_empty_or_reversed_custom_ranges():
    from app.schemas.activity import CandidateFilters

    for interval in ({}, {"minimum": 100, "maximum": 10}, {"minimum": -1}):
        with pytest.raises(ValidationError):
            CandidateFilters(follower_ranges=[interval])
    assert (
        CandidateFilters(follower_ranges=[{"minimum": 100}]).follower_ranges[0].maximum
        is None
    )


def test_query_budget_defaults_are_bounded_and_specific_unknown_is_opt_in():
    from app.schemas.activity import QueryCreate

    query = QueryCreate(providers=[{"platform": "youtube", "query": "indie"}])
    assert query.batch_target == 100
    assert query.result_limit == 600
    assert query.total_request_budget == 120
    assert not query.filters.include_unknown_country
    with pytest.raises(ValidationError):
        QueryCreate(
            providers=[{"platform": "youtube", "query": "indie"}], result_limit=601
        )
