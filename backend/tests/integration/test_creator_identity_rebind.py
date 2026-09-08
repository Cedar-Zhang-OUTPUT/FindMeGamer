from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select

from app.core.errors import APIError
from app.db.models.enums import AnalysisStage, JobMode, JobStatus, TargetType
from app.db.models.jobs import AnalysisJob
from app.db.models.profiles import CreatorContact, CreatorIdentityBinding, CreatorWork
from app.repositories.creator_identity import rebind_creator
from app.repositories.jobs import require_valid_succeeded_job_result
from app.integrations.errors import PermanentIntegrationError
from tests.integration.test_profiles_api import add_creator

NOW = datetime(2026, 9, 8, tzinfo=UTC)
OLD = "UCcreator123"


def creator(session):
    value = add_creator(
        session,
        channel_id=OLD,
        name="Original",
        favorite=True,
        manual_notes="Keep notes",
    )
    value.canonical_url = f"https://www.youtube.com/channel/{OLD}"
    value.platform_account_id = OLD
    value.manual_overrides = {"name": "Human name"}
    session.flush()
    return value


def rebind(session, value, platform="x", account_id="1234"):
    return rebind_creator(
        session,
        value,
        platform=platform,
        account_id=account_id,
        canonical_url=f"https://x.com/i/user/{account_id}",
        now=NOW,
    )


def test_rebind_preserves_uuid_manual_layers_and_archives_identity_evidence(session):
    value = creator(session)
    old_id = value.id
    contact = CreatorContact(
        creator_id=old_id,
        email="old@example.com",
        source_type="manual",
        is_manual=True,
        manual_overrides={"purpose": "Old"},
    )
    work = CreatorWork(
        creator_id=old_id,
        platform="youtube",
        origin="source",
        source_content_id="video1",
        source_fields={"title": "Old video"},
    )
    session.add_all([contact, work])
    session.flush()
    rebind(session, value)
    assert value.id == old_id and value.platform == "x"
    assert value.platform_account_id == "1234" and value.youtube_channel_id is None
    assert value.identity_revision == 1 and value.manual_revision == 1
    assert value.identity_changed_at == NOW
    assert value.manual_overrides == {"name": "Human name"}
    assert value.manual_notes == "Keep notes" and value.favorite
    assert value.current_facts == value.analysis == value.brief == {}
    assert value.last_analyzed_at is None and value.next_analysis_at is None
    assert not contact.is_active and contact.identity_revision == 0
    assert contact.manual_overrides == {"purpose": "Old"}
    assert work.identity_revision == 0 and work.source_fields == {"title": "Old video"}
    binding = session.get(CreatorIdentityBinding, (old_id, 0))
    assert binding.account_id == OLD and binding.platform == "youtube"


def test_identical_binding_is_noop(session):
    value = creator(session)
    rebind_creator(
        session,
        value,
        platform="youtube",
        account_id=OLD,
        canonical_url=value.canonical_url,
        now=NOW,
    )
    assert value.identity_revision == 0 and value.current_facts
    assert session.scalar(select(CreatorIdentityBinding)) is None


@pytest.mark.parametrize("target", [OLD, "UCnewcreator"])
def test_active_old_or_new_analysis_prevents_rebind(session, target):
    value = creator(session)
    session.add(
        AnalysisJob(
            target_type=TargetType.CREATOR,
            mode=JobMode.CREATE,
            status=JobStatus.QUEUED,
            canonical_target_id=target,
            canonical_url=f"https://www.youtube.com/channel/{target}",
        )
    )
    session.flush()
    with pytest.raises(APIError) as exc:
        rebind_creator(
            session,
            value,
            platform="youtube",
            account_id="UCnewcreator",
            canonical_url="https://www.youtube.com/channel/UCnewcreator",
            now=NOW,
        )
    assert exc.value.code == "creator_analysis_in_progress"
    assert value.identity_revision == 0 and value.youtube_channel_id == OLD


def test_historical_success_remains_valid_but_wrong_identity_does_not(session):
    value = creator(session)
    job = AnalysisJob(
        target_type=TargetType.CREATOR,
        mode=JobMode.CREATE,
        status=JobStatus.SUCCEEDED,
        stage=AnalysisStage.FINALIZING,
        completed_units=5,
        total_units=5,
        started_at=NOW,
        completed_at=NOW,
        canonical_target_id=OLD,
        canonical_url=value.canonical_url,
        profile_id=value.id,
        result_payload={"profile_id": str(value.id)},
    )
    job.created_at = NOW - timedelta(days=1)
    session.add(job)
    session.flush()
    require_valid_succeeded_job_result(session, job)
    rebind(session, value)
    # Force deferred database identity checks, not just Python projection.
    from sqlalchemy import text

    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    require_valid_succeeded_job_result(session, job)
    session.expunge(job)
    job.canonical_target_id = "UCwrongcreator"
    job.canonical_url = "https://www.youtube.com/channel/UCwrongcreator"
    with pytest.raises(PermanentIntegrationError):
        require_valid_succeeded_job_result(session, job)
    job.canonical_target_id = OLD
    job.canonical_url = f"https://www.youtube.com/channel/{OLD}"
    job.result_payload["unexpected"] = True
    with pytest.raises(PermanentIntegrationError):
        require_valid_succeeded_job_result(session, job)


def prepared_match(auth_client, session):
    from tests.integration.test_match_outreach_vertical_slice import (
        _seed_profiles,
        _configure_outreach,
        _finish_match,
    )

    game, value = _seed_profiles(session)
    _configure_outreach(auth_client)
    response = auth_client.post(
        "/api/v1/matches",
        headers={"Idempotency-Key": "rebind-match-create"},
        json={"game_id": str(game.id)},
    )
    assert response.status_code == 202, response.text
    match_id = UUID(response.json()["id"])
    _finish_match(session, match_id, value.id)
    return value, match_id


def test_pending_delivery_prevents_identity_change(auth_client, session):
    value, match_id = prepared_match(auth_client, session)
    response = auth_client.post(
        "/api/v1/outreach/send-batches",
        headers={"Idempotency-Key": "rebind-batch-send"},
        json={"match_task_id": str(match_id), "creator_ids": [str(value.id)]},
    )
    assert response.status_code == 201, response.text
    with pytest.raises(APIError) as exc:
        rebind(session, value)
    assert exc.value.code == "creator_delivery_in_progress"
    assert value.identity_revision == 0


def test_old_match_cannot_send_to_new_identity_contact(auth_client, session):
    from app.db.models.match import MatchTask

    value, match_id = prepared_match(auth_client, session)
    task = session.get(MatchTask, match_id)
    rebind_creator(
        session,
        value,
        platform="x",
        account_id="1234",
        canonical_url="https://x.com/i/user/1234",
        now=task.created_at + timedelta(seconds=1),
    )
    session.add(
        CreatorContact(
            creator_id=value.id,
            identity_revision=value.identity_revision,
            email="new@example.com",
            source_type="manual",
            is_manual=True,
        )
    )
    session.flush()
    response = auth_client.post(
        "/api/v1/outreach/send-batches",
        headers={"Idempotency-Key": "rebind-blocked-send"},
        json={"match_task_id": str(match_id), "creator_ids": [str(value.id)]},
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "creator_identity_changed"
