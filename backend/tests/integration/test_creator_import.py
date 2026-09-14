from datetime import UTC, datetime, timedelta
from decimal import Decimal
import importlib

import pytest
from sqlalchemy import select, func

from app.db.models.profiles import CreatorProfile, CreatorContact
from app.db.models.match import MatchScreeningRecord
from app.repositories.match import MatchRepository
from tests.unit.test_creator_import_contract import record, contract, supplied_analysis
from tests.integration.test_match_input_lock import _game


def importer():
    assert importlib.util.find_spec(
        "app.cli.import_creator_profiles"
    ), "import command missing"
    return importlib.import_module("app.cli.import_creator_profiles")


def test_import_dedup_and_manual_preservation(session):
    raw = record()
    raw["contacts"] = [
        dict(
            email="business@example.com",
            purpose="Business inquiries",
            source_url="https://example.com/contact",
            observed_at=raw["collected_at"],
        )
    ]
    data = contract().model_validate({"schema_version": 1, "records": [raw]})
    imp = importer()
    assert imp.import_profiles(session, data, dry_run=True)[0]["status"] == "ready"
    assert session.scalar(select(func.count()).select_from(CreatorProfile)) == 0
    imp.import_profiles(session, data)
    imp.import_profiles(session, data)
    assert session.scalar(select(func.count()).select_from(CreatorProfile)) == 1
    assert session.scalar(select(func.count()).select_from(CreatorContact)) == 1
    profile = session.scalar(select(CreatorProfile))
    assert profile.next_analysis_at is None
    assert profile.last_analyzed_at is None
    assert profile.source_status["twitch"] == "unavailable"
    profile.manual_overrides = {"creator.name": "Keep my name"}
    profile.manual_notes = "Keep my notes"
    session.flush()
    with pytest.raises(ValueError, match="manual"):
        imp.import_profiles(session, data)
    assert profile.manual_notes == "Keep my notes"
    assert profile.manual_overrides == {"creator.name": "Keep my name"}


def test_unknown_identity_dry_run_and_atomic_refusal(session):
    raw = record()
    raw.update(platform_account_id=None, account_id_source_url=None)
    data = contract().model_validate(
        {"collection_schema_version": 1, "creators": [record(), raw]}
    )
    imp = importer()
    assert (
        imp.import_profiles(session, data, dry_run=True)[1]["status"]
        == "needs_identity_resolution"
    )
    with pytest.raises(ValueError, match="identity"):
        imp.import_profiles(session, data)
    assert session.scalar(select(func.count()).select_from(CreatorProfile)) == 0


@pytest.mark.parametrize("platform", ["twitch", "instagram"])
def test_curated_analysis_enters_ordinary_match_and_expires(session, platform):
    now = datetime.now(UTC)
    raw = record(platform)
    raw["collected_at"] = now.isoformat()
    raw["bio_original"] = "Synthetic fixture about puzzle games."
    raw["observations"] = [
        dict(
            work_id=None,
            basis="profile_statement",
            observation_en="The fixture profile describes puzzle games.",
            source_url=raw["profile_url"],
            time_range=None,
            observed_at=now.isoformat(),
        )
    ]
    raw["analysis"] = supplied_analysis(now)
    data = contract().model_validate({"schema_version": 1, "records": [raw]})
    importer().import_profiles(session, data)
    game = _game()
    session.add(game)
    session.flush()
    profile = session.scalar(select(CreatorProfile))
    repo = MatchRepository(session, clock=lambda: now)
    task = repo.create_locked_task(game.id, 7, Decimal("0.7"))
    assert session.scalars(
        select(MatchScreeningRecord.creator_id).where(
            MatchScreeningRecord.match_task_id == task.id
        )
    ).all() == [profile.id]
    profile.last_analyzed_at = now - timedelta(days=31)
    session.flush()
    expired = repo.create_locked_task(game.id, 8, Decimal("0.7"))
    assert (
        session.scalars(
            select(MatchScreeningRecord).where(
                MatchScreeningRecord.match_task_id == expired.id
            )
        ).all()
        == []
    )


def test_fact_only_and_forged_provenance_do_not_enter_match(session):
    now = datetime.now(UTC)
    raw = record()
    data = contract().model_validate({"schema_version": 1, "records": [raw]})
    importer().import_profiles(session, data)
    game = _game()
    session.add(game)
    session.flush()
    profile = session.scalar(select(CreatorProfile))
    repo = MatchRepository(session, clock=lambda: now)
    for forge in (False, True):
        if forge:
            profile.last_analyzed_at = now
            profile.brief = supplied_analysis(now)["synthesis"]["creator_brief"]
            profile.source_status = {"twitch": "current", "freshness": "current"}
            session.flush()
        task = repo.create_locked_task(game.id, 7, Decimal("0.7"))
        assert (
            session.scalars(
                select(MatchScreeningRecord).where(
                    MatchScreeningRecord.match_task_id == task.id
                )
            ).all()
            == []
        )


def test_refresh_requires_explicit_unedited_conflict_policy(session):
    raw = record()
    raw["contacts"] = [
        {
            "email": "business@example.com",
            "purpose": "Business inquiries",
            "source_url": "https://example.com/contact",
            "observed_at": raw["collected_at"],
        }
    ]
    raw["analysis"] = supplied_analysis()
    data = contract().model_validate({"schema_version": 1, "records": [raw]})
    imp = importer()
    imp.import_profiles(session, data)
    raw["analysis"]["analyzed_at"] = datetime.now(UTC).isoformat()
    newer = contract().model_validate({"schema_version": 1, "records": [raw]})
    with pytest.raises(ValueError, match="conflict"):
        imp.import_profiles(session, newer)
    assert (
        imp.import_profiles(session, newer, on_conflict="replace-unedited")[0]["status"]
        == "imported"
    )
    profile = session.scalar(select(CreatorProfile))
    assert profile.last_analyzed_at == newer.records[0].analysis.analyzed_at
    assert session.scalar(select(func.count()).select_from(CreatorContact)) == 1


def test_batch_refresh_deduplicates_existing_contact_without_session_reload(session):
    from copy import deepcopy

    raw = record()
    raw["contacts"] = [
        {
            "email": "business@example.com",
            "purpose": "Business inquiries",
            "source_url": "https://example.com/contact",
            "observed_at": raw["collected_at"],
        }
    ]
    newer = deepcopy(raw)
    newer["collection_notes"] = "Additional synthetic collection context."
    data = contract().model_validate({"schema_version": 1, "records": [raw, newer]})
    importer().import_profiles(session, data, on_conflict="replace-unedited")
    assert session.scalar(select(func.count()).select_from(CreatorContact)) == 1


@pytest.mark.parametrize("platform", ["twitch", "instagram"])
def test_expired_import_and_natural_aging_hide_sources_without_reacquisition(
    session, auth_client, platform
):
    from app.repositories.profiles import ProfilesRepository

    old = datetime.now(UTC) - timedelta(days=31)
    raw = record(platform)
    raw["collected_at"] = (old - timedelta(days=1)).isoformat()
    raw["analysis"] = supplied_analysis(old)
    importer().import_profiles(
        session, contract().model_validate({"schema_version": 1, "records": [raw]})
    )
    profile = session.scalar(select(CreatorProfile))
    assert profile.source_status["freshness"] == "stale"
    assert profile.source_status[platform] == "unavailable"
    # Simulate natural aging before the periodic stale-marker has run.
    profile.source_status = {**profile.source_status, "freshness": "current"}
    session.flush()
    detail = auth_client.get(f"/api/v1/profiles/creators/{profile.id}").json()
    assert detail["current_facts"] == {}
    assert detail["analysis"] == {}
    assert detail["brief"] == {}
    assert detail["source_status"]["freshness"] == "stale"
    assert ProfilesRepository(session).mark_stale_creators(datetime.now(UTC)) == 1
    session.expire_all()
    assert profile.source_status["freshness"] == "stale"
    assert profile.source_status[platform] == "unavailable"
    assert profile.source_status["live_collection"] == "unavailable"
    assert profile.next_analysis_at is None
    assert ProfilesRepository(session).mark_stale_creators(datetime.now(UTC)) == 0
    assert (
        ProfilesRepository(session).list_due_profiles(now=datetime.now(UTC), limit=100)
        == []
    )
