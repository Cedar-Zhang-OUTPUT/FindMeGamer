import base64
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.profiles import CreatorContact, CreatorProfile, GameProfile
from tests.profile_policy_cases import (
    CONTEXT_METRIC_KEYS,
    NEAR_MISS_KEY_FORMS,
    RESTRICTED_ANCESTOR_FORMS,
    RESTRICTED_COMPACT_METRIC_FORMS,
    SECURITY_KEY_FORMS,
)


ANALYZED_AT = datetime(2026, 8, 30, 4, 5, tzinfo=timezone.utc)
NEXT_ANALYSIS_AT = datetime(2026, 9, 13, 4, 5, tzinfo=timezone.utc)
ROUTE_ERROR_CANARY = "ROUTE-SECRET-REPR-CANARY"


class RouteErrorCanaryObject:
    def __repr__(self) -> str:
        return f"RouteErrorCanaryObject(api_secret='{ROUTE_ERROR_CANARY}')"


def add_creator(
    session: Session,
    *,
    channel_id: str,
    name: str,
    favorite: bool = False,
    current_facts: dict[str, Any] | None = None,
    source_status: dict[str, Any] | None = None,
    profile_id: UUID | None = None,
    manual_notes: str | None = None,
) -> CreatorProfile:
    creator = CreatorProfile(
        id=profile_id or uuid4(),
        youtube_channel_id=channel_id,
        canonical_url=f"https://youtube.com/channel/{channel_id}",
        sort_name=name,
        current_facts=current_facts or {"channel_name": name},
        analysis={"content": {"primary_genres": ["strategy"]}},
        brief={"summary": f"{name} creator brief"},
        source_status=source_status or {"youtube": {"status": "current"}},
        model_metadata={"analysis_model": "test-model"},
        prompt_metadata={"version": "creator-v1"},
        favorite=favorite,
        manual_notes=manual_notes,
        last_analyzed_at=ANALYZED_AT,
        next_analysis_at=NEXT_ANALYSIS_AT,
    )
    session.add(creator)
    session.flush()
    return creator


def add_game(
    session: Session,
    *,
    app_id: str,
    name: str,
    favorite: bool = False,
    current_facts: dict[str, Any] | None = None,
    source_status: dict[str, Any] | None = None,
    profile_id: UUID | None = None,
) -> GameProfile:
    game = GameProfile(
        id=profile_id or uuid4(),
        steam_app_id=app_id,
        canonical_url=f"https://store.steampowered.com/app/{app_id}",
        sort_name=name,
        current_facts=current_facts or {"name": name, "genres": ["Strategy"]},
        analysis={"gameplay": {"core_loop": "Build and expand"}},
        brief={"summary": f"{name} game brief"},
        source_status=source_status or {"steam": {"status": "current"}},
        model_metadata={"analysis_model": "test-model"},
        prompt_metadata={"version": "game-v1"},
        favorite=favorite,
        last_analyzed_at=ANALYZED_AT,
        next_analysis_at=NEXT_ANALYSIS_AT,
    )
    session.add(game)
    session.flush()
    return game


def assert_error(response, *, status: int, code: str) -> None:
    expected_messages = {
        "profile_cursor_invalid": "The profile cursor is invalid.",
        "profile_not_found": "The requested profile was not found.",
        "profile_type_unknown": "The requested profile type is not supported.",
        "request_invalid": "The request is invalid.",
        "workspace_key_invalid": "A valid Workspace Access Key is required.",
    }
    assert response.status_code == status
    assert response.json() == {
        "error": {
            "code": code,
            "message": expected_messages[code],
            "retryable": False,
            "correlation_id": response.headers["x-correlation-id"],
        }
    }


@pytest.fixture
def creators(session: Session) -> list[CreatorProfile]:
    profiles = [
        add_creator(
            session,
            channel_id="strategy-alpha",
            name="Strategy Alpha",
            favorite=True,
        ),
        add_creator(
            session,
            channel_id="strategy-bravo",
            name="Strategy Bravo",
            favorite=True,
        ),
    ]
    return profiles


@pytest.fixture
def creator_id(session: Session) -> UUID:
    creator = add_creator(
        session,
        channel_id="contact-creator",
        name="Contact Creator",
    )
    creator.contacts.append(
        CreatorContact(
            email="public@example.com",
            source_type="youtube",
            source_url=creator.canonical_url,
            is_manual=False,
            validation_state="verified",
            priority=10,
            is_active=True,
        )
    )
    session.flush()
    return creator.id


def test_creator_library_search_collection_and_cursor(auth_client, creators) -> None:
    response = auth_client.get(
        "/api/v1/profiles/creators",
        params={"query": "strategy", "only_collection": True, "limit": 1},
    )
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    assert response.json()["next_cursor"] is not None


def test_manual_contact_takes_priority(auth_client, creator_id) -> None:
    response = auth_client.patch(
        f"/api/v1/profiles/creators/{creator_id}/manual",
        json={"contact_email": "team@example.com", "notes": "Warm lead"},
    )
    assert response.json()["contact"]["source"] == "manual"


def test_game_card_and_detail_are_distinct_typed_projections(
    auth_client, session: Session
) -> None:
    game = add_game(session, app_id="1001", name="Clockwork Kingdom", favorite=True)

    card_response = auth_client.get("/api/v1/profiles/games")
    detail_response = auth_client.get(f"/api/v1/profiles/games/{game.id}")

    assert card_response.status_code == 200
    assert card_response.json()["next_cursor"] is None
    card = card_response.json()["items"][0]
    assert card == {
        "type": "game",
        "profile_revision": 0,
        "manual_overrides": {},
        "id": str(game.id),
        "name": "Clockwork Kingdom",
        "steam_app_id": "1001",
        "canonical_url": "https://store.steampowered.com/app/1001",
        "favorite": True,
        "current_facts": {"name": "Clockwork Kingdom", "genres": ["Strategy"]},
        "brief": {"summary": "Clockwork Kingdom game brief"},
        "source_status": {"steam": {"status": "current"}},
        "last_analyzed_at": "2026-08-30T04:05:00Z",
        "next_analysis_at": "2026-09-13T04:05:00Z",
    }
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail == card | {
        "analysis": {"gameplay": {"core_loop": "Build and expand"}},
        "model_metadata": {"analysis_model": "test-model"},
        "prompt_metadata": {"version": "game-v1"},
    }
    assert "created_at" not in detail
    assert "updated_at" not in detail


def test_creator_card_and_detail_include_ordered_active_contacts_and_selected_contact(
    auth_client, session: Session
) -> None:
    creator = add_creator(
        session,
        channel_id="creator-card",
        name="Creator Card",
        favorite=True,
        manual_notes="Existing note",
    )
    creator.contacts.extend(
        [
            CreatorContact(
                email="inactive@example.com",
                source_type="website",
                source_url="https://creator.invalid/old",
                validation_state="verified",
                priority=100,
                is_active=False,
            ),
            CreatorContact(
                email="selected@example.com",
                source_type="website",
                source_url="https://creator.example/contact",
                purpose="Business inquiries",
                validation_state="verified",
                priority=10,
                is_active=True,
            ),
            CreatorContact(
                email="press@example.com",
                source_type="public_web_research",
                source_url="https://creator.example/press",
                purpose="Press requests",
                validation_state="unverified",
                priority=5,
                is_active=True,
            ),
        ]
    )
    session.flush()

    card = auth_client.get("/api/v1/profiles/creators").json()["items"][0]
    detail = auth_client.get(f"/api/v1/profiles/creators/{creator.id}").json()

    expected_contact = {
        "email": "selected@example.com",
        "source": "website",
        "source_url": "https://creator.example/contact",
        "purpose": "Business inquiries",
        "validation_state": "verified",
    }
    assert card == {
        "type": "creator",
        "profile_revision": 0,
        "manual_overrides": {},
        "id": str(creator.id),
        "name": "Creator Card",
        "youtube_channel_id": "creator-card",
        "canonical_url": "https://youtube.com/channel/creator-card",
        "favorite": True,
        "current_facts": {"channel_name": "Creator Card"},
        "brief": {"summary": "Creator Card creator brief"},
        "source_status": {"youtube": {"status": "current"}},
        "last_analyzed_at": "2026-08-30T04:05:00Z",
        "next_analysis_at": "2026-09-13T04:05:00Z",
        "contact": expected_contact,
        "contacts": [
            expected_contact,
            {
                "email": "press@example.com",
                "source": "public_web_research",
                "source_url": "https://creator.example/press",
                "purpose": "Press requests",
                "validation_state": "unverified",
            },
        ],
    }
    assert detail == card | {
        "analysis": {"content": {"primary_genres": ["strategy"]}},
        "model_metadata": {"analysis_model": "test-model"},
        "prompt_metadata": {"version": "creator-v1"},
        "manual_notes": "Existing note",
    }
    assert "inactive@example.com" not in json.dumps(detail)


def test_profile_json_projections_recursively_remove_sensitive_internal_keys(
    auth_client, session: Session
) -> None:
    game = add_game(
        session,
        app_id="sensitive-json",
        name="Safe Projection",
        current_facts={
            "name": "Safe Projection",
            "review_score": 91,
            "nested": [
                {
                    "public": "keep",
                    "hidden_total_score": 0.98,
                    "API-Key": "never-return-api-key",
                    "refreshToken": "never-return-token",
                    "id_token": "never-return-id-token",
                }
            ],
            "match_result": {
                "score": 0.95,
                "rank": 1,
                "backend_order": 0,
                "reasons": ["Strong fit"],
            },
        },
    )
    game.analysis = {
        "public_analysis": {"theme": "Automation"},
        "internal_match_scoring": {"numeric_score": 0.99},
        "db_password": "never-return-password",
    }
    game.brief = {
        "summary": "Public brief",
        "Hidden-Rank": 2,
        "backend_rank": 3,
        "numeric_total_score": 0.97,
        "service_credentials": {"username": "private"},
    }
    game.source_status = {
        "steam": {"status": "current"},
        "privateKey": "never-return-private-key",
    }
    game.model_metadata = {
        "analysis_model": "test-model",
        "api_secret": "never-return-secret",
    }
    game.prompt_metadata = {
        "version": "game-v1",
        "access_key": "never-return-access-key",
    }
    session.flush()

    card = auth_client.get("/api/v1/profiles/games").json()["items"][0]
    detail = auth_client.get(f"/api/v1/profiles/games/{game.id}").json()

    assert card["current_facts"] == {
        "name": "Safe Projection",
        "review_score": 91,
        "nested": [{"public": "keep"}],
        "match_result": {"reasons": ["Strong fit"]},
    }
    assert card["brief"] == {"summary": "Public brief"}
    assert card["source_status"] == {"steam": {"status": "current"}}
    assert detail["analysis"] == {"public_analysis": {"theme": "Automation"}}
    assert detail["model_metadata"] == {"analysis_model": "test-model"}
    assert detail["prompt_metadata"] == {"version": "game-v1"}
    for secret in (
        "never-return-api-key",
        "never-return-token",
        "never-return-id-token",
        "never-return-password",
        "never-return-private-key",
        "never-return-secret",
        "never-return-access-key",
    ):
        assert secret not in json.dumps(detail)


def test_profile_route_filters_security_keys_and_preserves_public_rank(
    auth_client, session: Session
) -> None:
    game = add_game(
        session,
        app_id="adversarial-security-json",
        name="Adversarial Projection",
        current_facts={
            "rank": "Gold tier",
            "score": 87,
            "authorization": "never-return-authorization",
            "jwt": "never-return-jwt",
            "passwd": "never-return-passwd",
            "nested": {
                "public": "keep",
                "token_payload": "never-return-token-payload",
                "Token Data": "never-return-token-data",
            },
            "match": {"rank": 1, "score": 0.99, "reason": "Public"},
        },
    )

    response = auth_client.get(f"/api/v1/profiles/games/{game.id}")

    assert response.status_code == 200
    assert response.json()["current_facts"] == {
        "rank": "Gold tier",
        "score": 87,
        "nested": {"public": "keep"},
        "match": {"reason": "Public"},
    }


def test_profile_route_applies_generated_security_and_metric_policy_matrix(
    auth_client, session: Session
) -> None:
    sensitive = {key: "never-return" for key in SECURITY_KEY_FORMS}
    near_misses = {key: "public-near-miss" for key in NEAR_MISS_KEY_FORMS}
    game = add_game(
        session,
        app_id="generated-policy-matrix",
        name="Generated Policy Matrix",
        current_facts={
            "rank": "Gold tier",
            "review_score": 91,
            "key": "public lookup key",
            **near_misses,
            **sensitive,
            "nested": {"public": "keep", **near_misses, **sensitive},
            **{
                ancestor: {
                    **{metric: 1 for metric in CONTEXT_METRIC_KEYS},
                    "scorecard_label": "Public scorecard",
                    "ordered_features": ["Public feature"],
                }
                for ancestor in RESTRICTED_ANCESTOR_FORMS
            },
            **{key: 1 for key in RESTRICTED_COMPACT_METRIC_FORMS},
        },
    )

    response = auth_client.get(f"/api/v1/profiles/games/{game.id}")

    assert response.status_code == 200
    assert response.json()["current_facts"] == {
        "rank": "Gold tier",
        "review_score": 91,
        "key": "public lookup key",
        **near_misses,
        "nested": {"public": "keep", **near_misses},
        **{
            ancestor: {
                "scorecard_label": "Public scorecard",
                "ordered_features": ["Public feature"],
            }
            for ancestor in RESTRICTED_ANCESTOR_FORMS
        },
    }


def test_profile_route_invalid_public_json_uses_safe_error_without_input_repr(
    auth_client, session: Session
) -> None:
    game = add_game(
        session,
        app_id="invalid-public-json",
        name="Invalid Public JSON",
    )
    # The response boundary must validate the value even though this key will
    # be removed from the public projection after validation succeeds.
    game.current_facts = {"api_secret": RouteErrorCanaryObject()}

    response = auth_client.get(f"/api/v1/profiles/games/{game.id}")

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "The request could not be completed.",
            "retryable": True,
            "correlation_id": response.headers["x-correlation-id"],
        }
    }
    assert ROUTE_ERROR_CANARY not in response.text


def test_duplicate_and_case_variant_names_page_without_skips_or_duplicates(
    auth_client, session: Session
) -> None:
    expected = [
        (UUID("00000000-0000-0000-0000-000000000002"), "Alpha"),
        (UUID("00000000-0000-0000-0000-000000000004"), "Alpha"),
        (UUID("00000000-0000-0000-0000-000000000003"), "Bravo"),
        (UUID("00000000-0000-0000-0000-000000000001"), "alpha"),
    ]
    for profile_id, name in reversed(expected):
        add_creator(
            session,
            profile_id=profile_id,
            channel_id=f"cursor-{profile_id}",
            name=name,
        )

    seen: list[tuple[str, str]] = []
    cursor = None
    cursors: list[str] = []
    for _ in range(2):
        response = auth_client.get(
            "/api/v1/profiles/creators",
            params={"limit": 2, **({"cursor": cursor} if cursor else {})},
        )
        assert response.status_code == 200
        body = response.json()
        seen.extend((item["id"], item["name"]) for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is not None:
            cursors.append(cursor)

    assert seen == [(str(profile_id), name) for profile_id, name in expected]
    assert len({profile_id for profile_id, _ in seen}) == 4
    assert cursor is None
    decoded = json.loads(
        base64.urlsafe_b64decode(cursors[0] + "=" * (-len(cursors[0]) % 4))
    )
    assert decoded["v"] == 1
    assert decoded["key"] == [
        "Alpha",
        "00000000-0000-0000-0000-000000000004",
    ]
    assert decoded["scope"] == {
        "profile_type": "creators",
        "query": "",
        "only_collection": False,
    }
    assert len(decoded["signature"]) == 64


@pytest.mark.parametrize(
    "cursor",
    [
        "not*base64",
        "a" * 2049,
        base64.urlsafe_b64encode(b"not-json").decode().rstrip("="),
        base64.urlsafe_b64encode(json.dumps(["Alpha"]).encode()).decode().rstrip("="),
        base64.urlsafe_b64encode(json.dumps(["Alpha", "not-a-uuid"]).encode())
        .decode()
        .rstrip("="),
        base64.urlsafe_b64encode(json.dumps(["Alpha", str(uuid4()), "extra"]).encode())
        .decode()
        .rstrip("="),
    ],
)
def test_malformed_cursor_uses_safe_error(auth_client, cursor: str) -> None:
    response = auth_client.get("/api/v1/profiles/creators", params={"cursor": cursor})

    assert_error(response, status=400, code="profile_cursor_invalid")


def test_tampered_cursor_tuple_is_rejected(auth_client, session: Session) -> None:
    creator = add_creator(
        session, channel_id="cursor-original", name="Original Cursor Name"
    )
    cursor = (
        base64.urlsafe_b64encode(
            json.dumps(["Tampered Name", str(creator.id)]).encode()
        )
        .decode()
        .rstrip("=")
    )

    response = auth_client.get("/api/v1/profiles/creators", params={"cursor": cursor})

    assert_error(response, status=400, code="profile_cursor_invalid")


def test_cursor_signature_rejects_a_different_existing_tuple(
    auth_client, session: Session
) -> None:
    first_id = UUID("20000000-0000-0000-0000-000000000001")
    second_id = UUID("20000000-0000-0000-0000-000000000002")
    add_creator(
        session,
        profile_id=first_id,
        channel_id="signed-cursor-first",
        name="Signed Cursor",
    )
    add_creator(
        session,
        profile_id=second_id,
        channel_id="signed-cursor-second",
        name="Signed Cursor",
    )
    cursor = auth_client.get("/api/v1/profiles/creators", params={"limit": 1}).json()[
        "next_cursor"
    ]
    payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    if isinstance(payload, list):
        payload[1] = str(second_id)
    else:
        payload["key"][1] = str(second_id)
    tampered = (
        base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )

    response = auth_client.get("/api/v1/profiles/creators", params={"cursor": tampered})

    assert_error(response, status=400, code="profile_cursor_invalid")


def test_cursor_is_bound_to_resource_type(auth_client, session: Session) -> None:
    shared_id = UUID("30000000-0000-0000-0000-000000000001")
    add_creator(
        session,
        profile_id=shared_id,
        channel_id="cross-resource-cursor",
        name="Cross Resource",
    )
    add_creator(
        session,
        channel_id="cross-resource-next",
        name="Cross Resource Next",
    )
    add_game(
        session,
        profile_id=shared_id,
        app_id="cross-resource-cursor",
        name="Cross Resource",
    )
    cursor = auth_client.get("/api/v1/profiles/creators", params={"limit": 1}).json()[
        "next_cursor"
    ]

    response = auth_client.get("/api/v1/profiles/games", params={"cursor": cursor})

    assert_error(response, status=400, code="profile_cursor_invalid")


@pytest.mark.parametrize(
    "first_params,reuse_params",
    [
        ({"limit": 1}, {"query": "alpha"}),
        ({"limit": 1}, {"only_collection": True}),
    ],
)
def test_cursor_is_bound_to_normalized_filter_scope(
    auth_client,
    session: Session,
    first_params: dict[str, object],
    reuse_params: dict[str, object],
) -> None:
    add_creator(
        session,
        channel_id="scope-alpha",
        name="Alpha Scope",
        favorite=True,
    )
    add_creator(
        session,
        channel_id="scope-bravo",
        name="Bravo Scope",
        favorite=True,
    )
    cursor = auth_client.get("/api/v1/profiles/creators", params=first_params).json()[
        "next_cursor"
    ]

    response = auth_client.get(
        "/api/v1/profiles/creators",
        params={**reuse_params, "cursor": cursor},
    )

    assert_error(response, status=400, code="profile_cursor_invalid")


def test_search_is_case_insensitive_and_treats_wildcards_literally(
    auth_client, session: Session
) -> None:
    for channel_id, name in [
        ("literal-percent", "100% STRATEGY"),
        ("ordinary-percent", "1000 strategy"),
        ("literal-underscore", "Under_score"),
        ("ordinary-underscore", "UnderXscore"),
    ]:
        add_creator(session, channel_id=channel_id, name=name)

    case_match = auth_client.get(
        "/api/v1/profiles/creators", params={"query": "strategy"}
    )
    percent_match = auth_client.get("/api/v1/profiles/creators", params={"query": "%"})
    underscore_match = auth_client.get(
        "/api/v1/profiles/creators", params={"query": "_"}
    )

    assert [item["name"] for item in case_match.json()["items"]] == [
        "100% STRATEGY",
        "1000 strategy",
    ]
    assert [item["name"] for item in percent_match.json()["items"]] == ["100% STRATEGY"]
    assert [item["name"] for item in underscore_match.json()["items"]] == [
        "Under_score"
    ]


def test_collection_filter_uses_shared_favorite_flag(
    auth_client, session: Session
) -> None:
    add_game(session, app_id="2001", name="Favorite Game", favorite=True)
    add_game(session, app_id="2002", name="Other Game", favorite=False)
    add_creator(
        session, channel_id="favorite-creator", name="Favorite Creator", favorite=True
    )
    add_creator(
        session, channel_id="other-creator", name="Other Creator", favorite=False
    )

    games = auth_client.get("/api/v1/profiles/games", params={"only_collection": True})
    creators = auth_client.get(
        "/api/v1/profiles/creators", params={"only_collection": True}
    )

    assert [item["name"] for item in games.json()["items"]] == ["Favorite Game"]
    assert [item["name"] for item in creators.json()["items"]] == ["Favorite Creator"]


@pytest.mark.parametrize("profile_type", ["games", "creators"])
def test_favorite_sets_explicit_desired_state_idempotently(
    auth_client, session: Session, profile_type: str
) -> None:
    profile = (
        add_game(session, app_id="3001", name="Favorite Target")
        if profile_type == "games"
        else add_creator(session, channel_id="favorite-target", name="Favorite Target")
    )

    first = auth_client.patch(
        f"/api/v1/profiles/{profile_type}/{profile.id}/favorite",
        json={"favorite": True},
    )
    repeated = auth_client.patch(
        f"/api/v1/profiles/{profile_type}/{profile.id}/favorite",
        json={"favorite": True},
    )
    unset = auth_client.patch(
        f"/api/v1/profiles/{profile_type}/{profile.id}/favorite",
        json={"favorite": False},
    )

    assert first.status_code == 200
    assert first.json()["type"] == profile_type.removesuffix("s")
    assert first.json()["favorite"] is True
    assert repeated.json()["favorite"] is True
    assert unset.json()["favorite"] is False
    session.expire_all()
    assert session.get(type(profile), profile.id).favorite is False


@pytest.mark.parametrize(
    "payload",
    [{}, {"favorite": None}, {"favorite": "yes"}, {"enabled": True}],
)
def test_favorite_requires_an_explicit_boolean(auth_client, payload) -> None:
    response = auth_client.patch(
        f"/api/v1/profiles/games/{uuid4()}/favorite", json=payload
    )

    assert_error(response, status=422, code="request_invalid")


def test_discovered_contact_selection_is_deterministic(
    auth_client, session: Session
) -> None:
    creator = add_creator(session, channel_id="contact-order", name="Contact Ordering")
    creator.contacts.extend(
        [
            CreatorContact(
                id=UUID("10000000-0000-0000-0000-000000000003"),
                email="lower-priority@example.com",
                source_type="youtube",
                validation_state="verified",
                priority=10,
                is_active=True,
            ),
            CreatorContact(
                id=UUID("10000000-0000-0000-0000-000000000002"),
                email="unverified@example.com",
                source_type="website",
                validation_state="unverified",
                priority=20,
                is_active=True,
            ),
            CreatorContact(
                id=UUID("10000000-0000-0000-0000-000000000001"),
                email="selected@example.com",
                source_type="social",
                source_url="https://social.example/creator",
                validation_state="verified",
                priority=20,
                is_active=True,
            ),
        ]
    )
    session.flush()

    detail = auth_client.get(f"/api/v1/profiles/creators/{creator.id}")

    assert detail.json()["contact"] == {
        "email": "selected@example.com",
        "purpose": None,
        "source": "social",
        "source_url": "https://social.example/creator",
        "validation_state": "verified",
    }


def test_manual_contact_update_preserves_discovered_contacts_and_updates_notes(
    auth_client, session: Session
) -> None:
    creator = add_creator(session, channel_id="manual-update", name="Manual Update")
    discovered = CreatorContact(
        email="discovered@example.com",
        source_type="website",
        source_url="https://manual.example/contact",
        validation_state="verified",
        priority=20,
        is_active=True,
    )
    creator.contacts.append(discovered)
    session.flush()

    first = auth_client.patch(
        f"/api/v1/profiles/creators/{creator.id}/manual",
        json={"contact_email": "first@example.com", "notes": "First note"},
    )
    second = auth_client.patch(
        f"/api/v1/profiles/creators/{creator.id}/manual",
        json={"contact_email": "second@example.com", "notes": "Updated note"},
    )
    session.expire_all()
    stored_contacts = session.scalars(
        select(CreatorContact).where(CreatorContact.creator_id == creator.id)
    ).all()

    assert first.json()["contact"]["source"] == "manual"
    assert second.json()["contact"] == {
        "email": "second@example.com",
        "purpose": None,
        "source": "manual",
        "source_url": None,
        "validation_state": "unverified",
    }
    assert second.json()["manual_notes"] == "Updated note"
    assert len(stored_contacts) == 2
    assert any(
        contact.email == "discovered@example.com"
        and not contact.is_manual
        and contact.is_active
        for contact in stored_contacts
    )
    assert (
        sum(contact.is_manual and contact.is_active for contact in stored_contacts) == 1
    )


def test_clearing_manual_contact_falls_back_to_discovered_and_can_clear_notes(
    auth_client, session: Session
) -> None:
    creator = add_creator(
        session,
        channel_id="manual-clear",
        name="Manual Clear",
        manual_notes="Old note",
    )
    creator.contacts.extend(
        [
            CreatorContact(
                email="manual@example.com",
                source_type="manual",
                is_manual=True,
                validation_state="unverified",
                priority=0,
                is_active=True,
            ),
            CreatorContact(
                email="fallback@example.com",
                source_type="youtube",
                source_url=creator.canonical_url,
                is_manual=False,
                validation_state="verified",
                priority=10,
                is_active=True,
            ),
        ]
    )
    session.flush()

    response = auth_client.patch(
        f"/api/v1/profiles/creators/{creator.id}/manual",
        json={"contact_email": None, "notes": None},
    )

    assert response.status_code == 200
    assert response.json()["contact"] == {
        "email": "fallback@example.com",
        "purpose": None,
        "source": "youtube",
        "source_url": creator.canonical_url,
        "validation_state": "verified",
    }
    assert response.json()["manual_notes"] is None
    session.expire_all()
    assert session.get(CreatorProfile, creator.id).manual_notes is None
    assert all(
        not contact.is_active
        for contact in session.scalars(
            select(CreatorContact).where(
                CreatorContact.creator_id == creator.id,
                CreatorContact.is_manual.is_(True),
            )
        )
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"contact_email": "not-an-email", "notes": "Note"},
        {"contact_email": "valid@example.com", "notes": 123},
    ],
)
def test_manual_update_validates_typed_body(
    auth_client, creator_id: UUID, payload: dict[str, object]
) -> None:
    response = auth_client.patch(
        f"/api/v1/profiles/creators/{creator_id}/manual", json=payload
    )

    assert_error(response, status=422, code="request_invalid")


@pytest.mark.parametrize(
    ("payload", "expected_email", "expected_notes"),
    [
        ({"contact_email": "valid@example.com"}, "valid@example.com", None),
        ({"notes": "Note"}, "public@example.com", "Note"),
    ],
)
def test_manual_update_accepts_an_omitted_nullable_field_as_null(
    auth_client,
    creator_id: UUID,
    payload: dict[str, object],
    expected_email: str,
    expected_notes: str | None,
) -> None:
    response = auth_client.patch(
        f"/api/v1/profiles/creators/{creator_id}/manual", json=payload
    )

    assert response.status_code == 200
    assert response.json()["contact"]["email"] == expected_email
    assert response.json()["manual_notes"] == expected_notes


@pytest.mark.parametrize(
    "stale_status",
    [
        {"status": "stale"},
        {"youtube": "STALE"},
        {"youtube": {"state": "stale"}},
    ],
)
def test_stale_creator_hides_current_facts_but_retains_identity_and_manual_data(
    auth_client, session: Session, stale_status: dict[str, Any]
) -> None:
    creator = add_creator(
        session,
        channel_id=f"stale-{uuid4()}",
        name="Stale Creator",
        current_facts={
            "channel_name": "Expired YouTube Name",
            "subscriber_count": 1_000_000,
        },
        source_status=stale_status,
        manual_notes="Keep this note",
    )
    creator.contacts.append(
        CreatorContact(
            email="manual-stale@example.com",
            source_type="manual",
            is_manual=True,
            validation_state="unverified",
            priority=0,
            is_active=True,
        )
    )
    session.flush()

    card = auth_client.get(
        "/api/v1/profiles/creators", params={"query": "Stale Creator"}
    ).json()["items"][0]
    detail = auth_client.get(f"/api/v1/profiles/creators/{creator.id}").json()

    assert card["name"] == "Stale Creator"
    assert card["youtube_channel_id"] == creator.youtube_channel_id
    assert card["current_facts"] == {}
    assert card["brief"] == {}
    assert card["source_status"] == stale_status
    assert card["contact"]["email"] == "manual-stale@example.com"
    assert detail["current_facts"] == {}
    assert detail["brief"] == {}
    assert detail["analysis"] == {}
    assert detail["manual_notes"] == "Keep this note"


def test_unrelated_stale_substatus_does_not_hide_current_youtube_facts(
    auth_client, session: Session
) -> None:
    creator = add_creator(
        session,
        channel_id="current-youtube-stale-visual",
        name="Current YouTube Creator",
        current_facts={
            "channel_name": "Current YouTube Creator",
            "subscriber_count": 42_000,
        },
        source_status={
            "youtube": {"status": "current"},
            "visual_analysis": {"status": "stale"},
        },
    )

    card = auth_client.get(
        "/api/v1/profiles/creators",
        params={"query": "Current YouTube Creator"},
    ).json()["items"][0]
    detail = auth_client.get(f"/api/v1/profiles/creators/{creator.id}").json()

    assert card["current_facts"] == {
        "channel_name": "Current YouTube Creator",
        "subscriber_count": 42_000,
    }
    assert detail["current_facts"] == card["current_facts"]


def test_stale_status_does_not_hide_game_facts(auth_client, session: Session) -> None:
    game = add_game(
        session,
        app_id="4001",
        name="Stale Marked Game",
        current_facts={"name": "Stale Marked Game", "review_summary": "Positive"},
        source_status={"steam": {"status": "stale"}},
    )

    card = auth_client.get("/api/v1/profiles/games").json()["items"][0]
    detail = auth_client.get(f"/api/v1/profiles/games/{game.id}").json()

    assert card["current_facts"]["review_summary"] == "Positive"
    assert detail["current_facts"]["review_summary"] == "Positive"


@pytest.mark.parametrize("profile_type", ["games", "creators"])
def test_unknown_profile_uses_stable_error(auth_client, profile_type: str) -> None:
    missing_id = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")

    detail = auth_client.get(f"/api/v1/profiles/{profile_type}/{missing_id}")
    favorite = auth_client.patch(
        f"/api/v1/profiles/{profile_type}/{missing_id}/favorite",
        json={"favorite": True},
    )

    assert_error(detail, status=404, code="profile_not_found")
    assert_error(favorite, status=404, code="profile_not_found")


@pytest.mark.parametrize("method", ["get", "patch"])
@pytest.mark.parametrize("profile_type", ["game", "creator", "players"])
def test_unknown_or_singular_profile_type_uses_stable_error(
    auth_client, method: str, profile_type: str
) -> None:
    profile_id = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    request = getattr(auth_client, method)
    kwargs = {"json": {"favorite": True}} if method == "patch" else {}
    path = f"/api/v1/profiles/{profile_type}/{profile_id}"
    if method == "patch":
        path += "/favorite"

    response = request(path, **kwargs)

    assert_error(response, status=404, code="profile_type_unknown")


def test_unknown_profile_type_wins_over_favorite_body_validation(auth_client) -> None:
    response = auth_client.patch(f"/api/v1/profiles/players/{uuid4()}/favorite")

    assert_error(response, status=404, code="profile_type_unknown")


def test_invalid_profile_uuid_uses_safe_validation_error(auth_client) -> None:
    response = auth_client.get("/api/v1/profiles/games/not-a-uuid")

    assert_error(response, status=422, code="request_invalid")


@pytest.mark.parametrize("limit", [0, 101])
@pytest.mark.parametrize("profile_type", ["games", "creators"])
def test_list_limit_is_bounded(auth_client, profile_type: str, limit: int) -> None:
    response = auth_client.get(
        f"/api/v1/profiles/{profile_type}", params={"limit": limit}
    )

    assert_error(response, status=422, code="request_invalid")


def test_search_query_length_is_bounded(auth_client) -> None:
    response = auth_client.get("/api/v1/profiles/games", params={"query": "a" * 256})

    assert_error(response, status=422, code="request_invalid")


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/api/v1/profiles/games", None),
        ("get", f"/api/v1/profiles/games/{uuid4()}", None),
        (
            "patch",
            f"/api/v1/profiles/games/{uuid4()}/favorite",
            {"favorite": True},
        ),
        (
            "patch",
            f"/api/v1/profiles/creators/{uuid4()}/manual",
            {"contact_email": None, "notes": None},
        ),
    ],
)
def test_profile_routes_require_workspace_authentication(
    client, method: str, path: str, payload: dict[str, object] | None
) -> None:
    request = getattr(client, method)
    response = request(path, **({"json": payload} if payload is not None else {}))

    assert_error(response, status=401, code="workspace_key_invalid")
