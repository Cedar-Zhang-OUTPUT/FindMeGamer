from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models.profiles import CreatorContact, CreatorProfile, CreatorWork
from app.discovery.library import evaluate_candidate, import_discovered_account
from app.repositories.creator_identity import rebind_creator
from app.repositories.creator_library import source_fields
from app.schemas.discovery import DiscoveredAccount, DiscoveredContent


NOW = datetime(2026, 9, 8, tzinfo=timezone.utc)


def account(**values):
    return DiscoveredAccount(
        platform="youtube",
        account_id="UCdiscovery",
        profile_url="https://www.youtube.com/channel/UCdiscovery",
        collected_at=NOW,
        **values,
    )


def content(**values):
    return DiscoveredContent(
        platform="youtube",
        content_id="video1",
        account_id="UCdiscovery",
        source_url="https://www.youtube.com/watch?v=video1",
        collected_at=NOW,
        **values,
    )


def test_import_deduplicates_and_preserves_human_analysis_and_verified_work(session):
    first = account(display_name="Source", follower_count=123, country="US")
    creator = import_discovered_account(session, first, [content(title="First")])
    assert creator.youtube_channel_id == first.account_id
    assert creator.next_analysis_at is None
    creator.manual_overrides = {"name": "Human", "follower_count": 999}
    creator.analysis = {"old": "AI"}
    creator.brief = {"old": "brief"}
    creator.last_analyzed_at = NOW - timedelta(days=5)
    creator.next_analysis_at = NOW + timedelta(days=5)
    creator.source_status = {"analysis": "ok"}
    contact = CreatorContact(
        creator_id=creator.id,
        email="hello@example.com",
        source_type="manual",
        is_manual=True,
        is_active=True,
        validation_state="valid",
        identity_revision=creator.identity_revision,
    )
    session.add(contact)
    work = session.scalar(
        select(CreatorWork).where(CreatorWork.creator_id == creator.id)
    )
    work.manual_overrides = {"content_title": "Human title"}
    work.source_fields = work.source_fields | {
        "content_type": "gameplay",
        "evidence_excerpt": "verified evidence",
    }
    same = import_discovered_account(
        session,
        account(display_name="New"),
        [content(title="New title"), content(title="New title")],
    )
    assert same.id == creator.id
    assert same.manual_overrides == {"name": "Human", "follower_count": 999}
    assert same.analysis == {"old": "AI"} and same.brief == {"old": "brief"}
    assert same.last_analyzed_at == NOW - timedelta(days=5)
    assert same.next_analysis_at == NOW + timedelta(days=5)
    assert same.source_status["analysis"] == "ok"
    assert same.current_facts["subscriber_count"] == 123
    assert source_fields(same).follower_count_collected_at == NOW
    assert work.source_fields["content_type"] == "gameplay"
    assert work.source_fields["evidence_excerpt"] == "verified evidence"
    assert work.manual_overrides == {"content_title": "Human title"}
    assert len(session.scalars(select(CreatorWork)).all()) == 1
    assert contact.is_active and contact.validation_state == "valid"


def test_conflicting_manual_url_and_archived_binding_are_not_imported(session):
    value = account()
    manual = CreatorProfile(
        platform="youtube", canonical_url=value.profile_url, sort_name="Manual"
    )
    session.add(manual)
    session.flush()
    assert import_discovered_account(session, value, []) is None
    session.delete(manual)
    session.flush()
    creator = import_discovered_account(session, value, [content()])
    rebind_creator(
        session,
        creator,
        platform="youtube",
        account_id="UCnewaccount",
        canonical_url="https://www.youtube.com/channel/UCnewaccount",
        now=NOW,
    )
    assert import_discovered_account(session, value, []) is None
    assert (
        creator.platform_account_id == "UCnewaccount" and creator.identity_revision == 1
    )


@pytest.mark.parametrize(
    "filters,expected",
    [
        ({}, True),
        ({"countries": ["US"]}, False),
        ({"countries": ["US"], "include_unknown_country": True}, True),
        ({"languages": ["en"]}, False),
        ({"languages": ["en"], "include_unknown_language": True}, True),
        ({"follower_ranges": [{"minimum": 1}]}, False),
        (
            {"follower_ranges": [{"minimum": 1}], "include_unknown_followers": True},
            True,
        ),
    ],
)
def test_unknown_filters_are_explicit(session, filters, expected):
    value = account(location_text="United States")
    creator = import_discovered_account(session, value, [])
    accepted, notes = evaluate_candidate(
        session,
        creator,
        value,
        [],
        filters | {"pending_country_labels": ["North America"]},
    )
    assert accepted is expected
    assert set(notes["unknown_fields"]) == {"country", "language", "followers"}
    assert notes["pending_country_labels"] == ["North America"]
    assert notes["evidence_status"] == "unverified"


def test_effective_fields_ranges_and_current_valid_contacts(session):
    value = account(follower_count=50, country="US")
    creator = import_discovered_account(session, value, [])
    creator.manual_overrides = {"country_code": "GB", "follower_count": 200}
    filters = {
        "countries": ["GB"],
        "languages": ["en"],
        "follower_ranges": [{"maximum": 10}, {"minimum": 200, "maximum": 300}],
        "contact": "missing",
    }
    assert evaluate_candidate(
        session, creator, value, [content(language="en")], filters
    )[0]
    session.add(
        CreatorContact(
            creator_id=creator.id,
            email="hello@example.com",
            source_type="manual",
            is_active=True,
            validation_state="valid",
            identity_revision=creator.identity_revision,
        )
    )
    session.flush()
    assert evaluate_candidate(
        session,
        creator,
        value,
        [content(language="en")],
        filters | {"contact": "available"},
    )[0]
    assert not evaluate_candidate(
        session, creator, value, [content(language="en")], filters
    )[0]
    creator.identity_revision += 1
    assert evaluate_candidate(
        session, creator, value, [content(language="en")], filters
    )[0]


def test_old_or_missing_metadata_does_not_erase_recent_public_facts(session):
    creator = import_discovered_account(
        session, account(display_name="New", follower_count=20), [content(title="New")]
    )
    older = account(display_name="Old", follower_count=1).model_copy(
        update={"collected_at": NOW - timedelta(days=1)}
    )
    old_content = content(title="Old").model_copy(
        update={"collected_at": NOW - timedelta(days=1)}
    )
    import_discovered_account(session, older, [old_content])
    assert creator.current_facts["title"] == "New"
    assert creator.current_facts["subscriber_count"] == 20
    work = session.scalar(
        select(CreatorWork).where(CreatorWork.creator_id == creator.id)
    )
    assert work.source_fields["content_title"] == "New"


@pytest.mark.parametrize(
    "active,state", [(False, "valid"), (True, "unverified"), (True, "invalid")]
)
def test_unusable_contacts_do_not_satisfy_availability(session, active, state):
    value = account()
    creator = import_discovered_account(session, value, [])
    session.add(
        CreatorContact(
            creator_id=creator.id,
            email="hello@example.com",
            source_type="manual",
            is_active=active,
            validation_state=state,
            identity_revision=creator.identity_revision,
        )
    )
    session.flush()
    assert not evaluate_candidate(
        session, creator, value, [], {"contact": "available"}
    )[0]


def test_content_language_requires_same_account_and_respects_manual_language(session):
    value = account()
    creator = import_discovered_account(session, value, [])
    unrelated = content(language="en").model_copy(update={"account_id": "UCother"})
    assert not evaluate_candidate(
        session, creator, value, [unrelated], {"languages": ["en"]}
    )[0]
    creator.manual_overrides = {"languages": ["fr"]}
    assert not evaluate_candidate(
        session, creator, value, [content(language="en")], {"languages": ["en"]}
    )[0]
    assert evaluate_candidate(session, creator, value, [], {"languages": ["fr"]})[0]


def test_unusable_public_metadata_preserves_known_values(session):
    creator = import_discovered_account(
        session, account(country="US", follower_count=100), []
    )
    import_discovered_account(
        session, account(country="Unknown location", follower_count=-1), []
    )
    assert source_fields(creator).country_code == "US"
    assert source_fields(creator).follower_count == 100


@pytest.mark.parametrize("language", ["und", "zxx", "UND"])
def test_provider_non_language_codes_are_unknown(session, language):
    value = DiscoveredAccount(
        platform="x",
        account_id="123",
        profile_url="https://x.com/i/user/123",
        collected_at=NOW,
    )
    item = DiscoveredContent(
        platform="x",
        content_id="456",
        account_id="123",
        source_url="https://x.com/i/status/456",
        language=language,
        collected_at=NOW,
    )
    creator = import_discovered_account(session, value, [item])
    filters = {"languages": ["en"]}
    accepted, notes = evaluate_candidate(
        session, creator, value, [item], filters | {"include_unknown_language": True}
    )
    assert accepted
    assert "language" in notes["unknown_fields"]
    assert not evaluate_candidate(session, creator, value, [item], filters)[0]
    # Unknown content does not erase actual language evidence from other content.
    known = item.model_copy(update={"content_id": "789", "language": "fr"})
    accepted, notes = evaluate_candidate(
        session,
        creator,
        value,
        [item, known],
        filters | {"include_unknown_language": True},
    )
    assert not accepted
    assert "language" not in notes["unknown_fields"]
