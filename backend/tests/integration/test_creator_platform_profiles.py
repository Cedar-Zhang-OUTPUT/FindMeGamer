from datetime import UTC, datetime, timedelta

from app.db.models.profiles import CreatorProfile
from app.repositories.profiles import ProfilesRepository
from app.analysis.targets import CanonicalTarget
from app.db.models.enums import JobMode, TargetType
from app.repositories.jobs import JobsRepository
from app.repositories.match import MatchRepository
from app.schemas.ai_creator import CreatorBrief
from tests.integration.test_match_input_lock import _creator_brief


def test_existing_youtube_constructor_backfills_public_identity(auth_client, session):
    profile = CreatorProfile(
        youtube_channel_id="UCidentity123",
        canonical_url="https://www.youtube.com/channel/UCidentity123",
        sort_name="Legacy",
    )
    session.add(profile)
    session.flush()
    detail = auth_client.get(f"/api/v1/profiles/creators/{profile.id}").json()
    assert detail["platform"] == "youtube"
    assert detail["platform_account_id"] == "UCidentity123"
    assert detail["youtube_channel_id"] == "UCidentity123"


def test_platform_profiles_remain_distinct_and_edit_without_youtube_id(
    auth_client, session
):
    profiles = [
        CreatorProfile(
            platform=platform,
            platform_account_id="12345",
            canonical_url=url,
            sort_name=platform,
            current_facts={"title": platform},
        )
        for platform, url in [
            ("x", "https://x.com/i/user/12345"),
            ("twitch", "https://www.twitch.tv/example"),
        ]
    ]
    session.add_all(profiles)
    session.flush()
    assert profiles[0].id != profiles[1].id
    for profile in profiles:
        response = auth_client.patch(
            f"/api/v1/profiles/creator/{profile.id}/edit",
            json={
                "expected_revision": 0,
                "changes": {"facts.title": "Human title"},
                "reset_fields": [],
            },
        )
        assert response.status_code == 200
        detail = auth_client.get(f"/api/v1/profiles/creators/{profile.id}").json()
        assert detail["platform"] == profile.platform
        assert detail["platform_account_id"] == "12345"
        assert detail["youtube_channel_id"] is None
        assert detail["name"] == "Human title"
        assert profile.current_facts == {"title": profile.platform}
    cards = auth_client.get("/api/v1/profiles/creators").json()["items"]
    assert {item["platform"] for item in cards} == {"x", "twitch"}


def test_unavailable_platforms_are_not_scheduled_or_marked_youtube_stale(session):
    now = datetime.now(UTC)
    for platform in ("twitch", "instagram"):
        session.add(
            CreatorProfile(
                platform=platform,
                platform_account_id="12345",
                canonical_url=f"https://{platform}.com/example",
                sort_name=platform,
                last_analyzed_at=now - timedelta(days=40),
                next_analysis_at=now - timedelta(days=1),
                source_status={platform: "available"},
            )
        )
    session.flush()
    repository = ProfilesRepository(session)
    assert repository.list_due_profiles(now=now, limit=100) == []
    assert repository.mark_stale_creators(now) == 0


def test_generic_job_lookup_reuses_correct_platform_profile(session):
    profiles = [
        CreatorProfile(
            platform=platform,
            platform_account_id="12345",
            canonical_url=url,
            sort_name=platform,
        )
        for platform, url in [
            ("x", "https://x.com/i/user/12345"),
            ("twitch", "https://www.twitch.tv/example"),
        ]
    ]
    session.add_all(profiles)
    session.flush()
    result = JobsRepository(session).create_or_reuse_job(
        CanonicalTarget(
            target_type=TargetType.CREATOR,
            canonical_id="x:12345",
            canonical_url=profiles[0].canonical_url,
        ),
        mode=JobMode.CREATE,
        correlation_id=None,
    )
    assert result.existing_profile_id == profiles[0].id
    assert result.job is None


def test_new_match_snapshot_retains_generic_identity(session):
    profile = CreatorProfile(
        platform="x",
        platform_account_id="12345",
        canonical_url="https://x.com/i/user/12345",
        sort_name="Example",
    )
    session.add(profile)
    session.flush()
    snapshot = MatchRepository._creator_snapshot(
        profile, creator_brief=CreatorBrief.model_validate(_creator_brief("Unknown"))
    )
    assert snapshot["platform"] == "x"
    assert snapshot["platform_account_id"] == "12345"
    assert snapshot["youtube_channel_id"] is None
