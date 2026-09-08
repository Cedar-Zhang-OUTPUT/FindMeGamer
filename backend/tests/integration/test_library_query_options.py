from datetime import UTC, datetime, timedelta

from app.db.models.profiles import (
    CreatorProfile,
    CreatorWork,
    CreatorContact,
    GameProfile,
)

NOW = datetime(2026, 9, 8, tzinfo=UTC)


def creator(
    session, key, name, *, followers=None, platform="youtube", languages=(), days=0
):
    row = CreatorProfile(
        platform=platform,
        platform_account_id=key,
        youtube_channel_id=key if platform == "youtube" else None,
        canonical_url=f"https://example.com/{key}",
        sort_name=name,
        manual_overrides={
            "name": name,
            "follower_count": followers,
            "languages": list(languages),
        },
        created_at=NOW + timedelta(days=days),
        updated_at=NOW + timedelta(days=days),
    )
    session.add(row)
    session.flush()
    return row


def work(session, owner, title, *, days=0, historical=False, **fields):
    row = CreatorWork(
        creator_id=owner.id,
        platform=owner.platform,
        origin="manual",
        identity_revision=(
            owner.identity_revision - 1 if historical else owner.identity_revision
        ),
        manual_overrides={
            "content_title": title,
            "published_at": (NOW + timedelta(days=days)).isoformat(),
            "source_url": f"https://example.com/work/{title}",
            **fields,
        },
    )
    session.add(row)
    session.flush()
    return row


def test_creator_multiselect_and_followers_sort_before_pagination(auth_client, session):
    creator(session, "UCunknown", "A Unknown", languages=["English"])
    small = creator(session, "UCsmall", "B Small", followers=10, languages=["English"])
    big = creator(
        session, "123", "C Big", followers=1000, platform="x", languages=["Japanese"]
    )
    creator(
        session,
        "456",
        "D Excluded",
        followers=9999,
        platform="twitch",
        languages=["English"],
    )
    response = auth_client.get(
        "/api/v2/library/creators",
        params=[
            ("platforms", "youtube"),
            ("platforms", "x"),
            ("languages", "English"),
            ("languages", "Japanese"),
            ("sort", "followers"),
            ("limit", "1"),
        ],
    )
    assert response.status_code == 200
    assert response.json()["total"] == 3
    assert response.json()["items"][0]["id"] == str(big.id)
    second = auth_client.get(
        "/api/v2/library/creators",
        params={"platforms": "youtube", "sort": "followers", "limit": 1},
    )
    assert second.json()["items"][0]["id"] == str(small.id)


def test_recent_summary_sort_ignores_historical_identity_and_counts_current_contacts(
    auth_client, session
):
    first = creator(session, "UCfirst", "A Old", followers=1, days=1)
    second = creator(session, "UCsecond", "B Recent", days=2)
    first.identity_revision = 1
    work(session, first, "historical", days=20, historical=True)
    work(session, first, "older", days=1)
    latest = work(session, second, "latest", days=4)
    session.add_all(
        [
            CreatorContact(
                creator_id=second.id,
                email="business@example.com",
                source_type="manual",
                purpose="Business",
            ),
            CreatorContact(
                creator_id=second.id,
                email="inactive@example.com",
                source_type="manual",
                is_active=False,
            ),
        ]
    )
    session.flush()
    response = auth_client.get(
        "/api/v2/library/creators", params={"sort": "recent_publish", "limit": 1}
    )
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["id"] == str(second.id)
    assert item["recent_works"][0]["id"] == str(latest.id)
    assert item["active_email_count"] == 1
    assert item["contact_status"] == "available"
    assert item["updated_at"] is not None
    added = auth_client.get(
        "/api/v2/library/creators", params={"sort": "recent_added", "limit": 1}
    )
    assert added.json()["items"][0]["id"] == str(second.id)


def test_creator_search_relevance_prefers_name_without_game_score(auth_client, session):
    creator(session, "UCmisc", "A Misc", languages=["English"])
    matched = creator(session, "UCname", "Puzzle", languages=["English"])
    other = creator(session, "UCwork", "A Work")
    work(session, other, "Puzzle walkthrough")
    response = auth_client.get(
        "/api/v2/library/creators",
        params={"query": "Puzzle", "sort": "relevance", "limit": 1},
    )
    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert response.json()["items"][0]["id"] == str(matched.id)
    assert "score" not in response.json()["items"][0]


def test_game_effective_website_filter_and_global_sort(auth_client, session):
    first = GameProfile(
        steam_app_id="123",
        canonical_url="https://store.steampowered.com/app/123/",
        sort_name="A Game",
        manual_overrides={"name": "A Game", "website_url": None},
        created_at=NOW,
        updated_at=NOW,
    )
    second = GameProfile(
        canonical_url="",
        sort_name="B Game",
        manual_overrides={"name": "B Game", "website_url": "https://example.com/game"},
        created_at=NOW + timedelta(days=2),
        updated_at=NOW + timedelta(days=3),
    )
    session.add_all([first, second])
    session.flush()
    available = auth_client.get(
        "/api/v2/library/games", params={"website_status": "available", "limit": 1}
    )
    assert available.status_code == 200
    assert available.json()["total"] == 1
    assert available.json()["items"][0]["id"] == str(second.id)
    missing = auth_client.get(
        "/api/v2/library/games", params={"website_status": "missing"}
    )
    assert [v["id"] for v in missing.json()["items"]] == [str(first.id)]
    for sort in ("recent_updated", "recent_added"):
        recent = auth_client.get(
            "/api/v2/library/games", params={"sort": sort, "limit": 1}
        )
        assert recent.json()["items"][0]["id"] == str(second.id)
        assert recent.json()["items"][0]["updated_at"] is not None


def test_query_option_validation_does_not_silently_ignore_invalid_choices(auth_client):
    assert (
        auth_client.get(
            "/api/v2/library/creators", params={"platforms": "unknown"}
        ).status_code
        == 422
    )
    assert (
        auth_client.get(
            "/api/v2/library/creators", params={"sort": "unknown"}
        ).status_code
        == 422
    )
    assert (
        auth_client.get(
            "/api/v2/library/games", params={"website_status": "unknown"}
        ).status_code
        == 422
    )
