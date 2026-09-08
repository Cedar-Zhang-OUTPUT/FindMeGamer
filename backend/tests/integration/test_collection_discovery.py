import pytest

from app.repositories.collection_settings import update_collection
from app.repositories.discovery import start_batch
from tests.integration.test_discovery_runtime import (
    make_query,
    page,
    factories,
    runtime,
)


def test_disable_inflight_preserves_page_cursor_and_requires_explicit_continue(session):
    query = make_query(session)
    batch = start_batch(session, query)
    session.commit()
    calls = []

    def first(request):
        calls.append(request)
        assert len(calls) == 1, "Disabled provider fetched another page"
        update_collection(session, "youtube", False)
        session.commit()
        return page(request, ["UCaaaaaaa"], True)

    runtime()(batch.id, **factories(session, first))
    assert query.result_count == 1
    assert query.status == "paused"
    assert batch.reason == "collection_disabled"
    assert query.provider_states["youtube"]["cursor"]["token"] == "next"
    assert query.provider_states["youtube"]["status"] == "more"
    assert query.provider_states["youtube"]["blocked_reason"] == "collection_disabled"
    update_collection(session, "youtube", True)
    session.commit()
    assert len(calls) == 1
    assert query.status == "paused"
    resumed = start_batch(session, query)
    session.commit()

    def second(request):
        assert request.cursor.token == "next"
        return page(request, ["UCbbbbbbb"])

    runtime()(resumed.id, **factories(session, second))
    assert query.result_count == 2
    assert "blocked_reason" not in query.provider_states["youtube"]


def test_disabled_youtube_does_not_stop_x_or_erase_other_provider_state(session):
    query = make_query(
        session,
        providers=[
            {"platform": "youtube", "query": "game", "page_size": 2},
            {"platform": "x", "query": "game", "page_size": 10},
        ],
    )
    update_collection(session, "youtube", False)
    batch = start_batch(session, query)
    session.commit()

    def only_x(request):
        assert request.platform == "x"
        return page(request, ["123456789"])

    runtime()(batch.id, **factories(session, only_x))
    assert query.result_count == 1
    assert query.provider_states["x"]["status"] == "exhausted"
    assert query.provider_states["youtube"]["blocked_reason"] == "collection_disabled"
    assert query.status == "paused"
    assert batch.reason == "collection_disabled"


@pytest.mark.parametrize("enabled", [False, True])
def test_unimplemented_preset_is_recoverable_without_paid_attempt(session, enabled):
    query = make_query(session, providers=[{"platform": "twitch", "query": "game"}])
    update_collection(session, "twitch", enabled)
    batch = start_batch(session, query)
    session.commit()
    runtime()(
        batch.id,
        **factories(session, lambda req: pytest.fail("Preset made a paid request")),
    )
    assert query.status == "paused"
    assert batch.reason == "no_available_sources"
    assert query.requests_reserved == 0
    assert query.provider_states["twitch"]["status"] == "not_supported"
