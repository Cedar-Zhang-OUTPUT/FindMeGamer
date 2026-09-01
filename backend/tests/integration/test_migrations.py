from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.enums import JobStatus, TargetType
from app.db.models.idempotency import IdempotencyRecord
from app.db.models.jobs import AnalysisJob
from app.db.models.profiles import CreatorProfile, GameProfile
from app.db.models.settings import SharedSettings


CORE_TABLES = {
    "game_profiles",
    "creator_profiles",
    "creator_contacts",
    "analysis_jobs",
    "shared_settings",
    "service_secrets",
    "idempotency_records",
}


def test_initial_migration_creates_core_tables(database_inspector) -> None:
    names = set(database_inspector.get_table_names())
    assert CORE_TABLES <= names


def test_initial_migration_seeds_shared_defaults(session: Session) -> None:
    settings = session.scalar(select(SharedSettings))
    assert settings is not None
    assert settings.creator_interval_days == 14
    assert settings.game_interval_days == 30
    assert settings.recommended_match_threshold == Decimal("0.70")
    assert settings.smtp_rate_per_minute == 10


@pytest.mark.parametrize(
    ("field", "value", "constraint_name"),
    [
        ("creator_interval_days", 0, "ck_shared_settings_creator_interval_days"),
        ("creator_interval_days", 31, "ck_shared_settings_creator_interval_days"),
        ("game_interval_days", 0, "ck_shared_settings_game_interval_days"),
        ("game_interval_days", 91, "ck_shared_settings_game_interval_days"),
    ],
)
def test_shared_intervals_are_enforced_by_postgresql(
    session: Session, field: str, value: int, constraint_name: str
) -> None:
    settings = SharedSettings(**{field: value})
    savepoint = session.begin_nested()
    try:
        session.add(settings)
        with pytest.raises(IntegrityError) as error:
            session.flush()
        assert error.value.orig.diag.constraint_name == constraint_name
    finally:
        savepoint.rollback()


@pytest.mark.parametrize(
    ("column", "value", "constraint_name"),
    [
        ("target_type", "publisher", "target_type"),
        ("mode", "refresh", "job_mode"),
        ("status", "pending", "job_status"),
        ("stage", "scoring", "analysis_stage"),
    ],
)
def test_analysis_job_enums_are_enforced_by_postgresql(
    session: Session, column: str, value: str, constraint_name: str
) -> None:
    values = {
        "target_type": "game",
        "mode": "create",
        "status": "queued",
        "stage": "fetching_data",
    }
    values[column] = value
    savepoint = session.begin_nested()
    try:
        with pytest.raises(IntegrityError) as error:
            session.execute(
                text(
                    """
                    INSERT INTO analysis_jobs (
                        id, target_type, canonical_target_id, canonical_url,
                        mode, status, stage
                    ) VALUES (
                        :id, :target_type, :canonical_target_id, :canonical_url,
                        :mode, :status, :stage
                    )
                    """
                ),
                {
                    "id": uuid4(),
                    "canonical_target_id": f"invalid-enum-{uuid4()}",
                    "canonical_url": "https://example.com/invalid-enum",
                    **values,
                },
            )
        assert error.value.orig.diag.constraint_name == constraint_name
    finally:
        savepoint.rollback()


def test_only_one_active_job_exists_per_target(session: Session) -> None:
    target_id = f"active-{uuid4()}"
    session.add(_job(target_id, JobStatus.QUEUED))
    session.flush()

    savepoint = session.begin_nested()
    try:
        session.add(_job(target_id, JobStatus.RUNNING))
        with pytest.raises(IntegrityError) as error:
            session.flush()
        assert error.value.orig.diag.constraint_name == "uq_analysis_jobs_active_target"
    finally:
        savepoint.rollback()


def test_completed_job_history_allows_a_new_active_job(session: Session) -> None:
    target_id = f"history-{uuid4()}"
    session.add_all(
        [
            _job(target_id, JobStatus.SUCCEEDED),
            _job(target_id, JobStatus.FAILED),
            _job(target_id, JobStatus.QUEUED),
        ]
    )
    session.flush()
    count = session.scalar(
        select(func.count())
        .select_from(AnalysisJob)
        .where(AnalysisJob.canonical_target_id == target_id)
    )
    assert count == 3


@pytest.mark.parametrize(
    "first,duplicate",
    [
        (
            GameProfile(
                steam_app_id="duplicate-game",
                canonical_url="https://store.steampowered.com/app/duplicate-game",
                sort_name="Game",
            ),
            GameProfile(
                steam_app_id="duplicate-game",
                canonical_url="https://store.steampowered.com/app/duplicate-game",
                sort_name="Game copy",
            ),
        ),
        (
            CreatorProfile(
                youtube_channel_id="duplicate-creator",
                canonical_url="https://youtube.com/channel/duplicate-creator",
                sort_name="Creator",
            ),
            CreatorProfile(
                youtube_channel_id="duplicate-creator",
                canonical_url="https://youtube.com/channel/duplicate-creator",
                sort_name="Creator copy",
            ),
        ),
    ],
)
def test_profile_identifiers_are_unique(session: Session, first, duplicate) -> None:
    session.add(first)
    session.flush()
    savepoint = session.begin_nested()
    try:
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            session.flush()
    finally:
        savepoint.rollback()


def test_idempotency_keys_are_unique(session: Session) -> None:
    key = f"idempotency-{uuid4()}"
    session.add(_idempotency_record(key))
    session.flush()
    savepoint = session.begin_nested()
    try:
        session.add(_idempotency_record(key))
        with pytest.raises(IntegrityError):
            session.flush()
    finally:
        savepoint.rollback()


def test_service_secrets_store_only_encrypted_material(database_inspector) -> None:
    columns = {
        column["name"]: column
        for column in database_inspector.get_columns("service_secrets")
    }
    assert {"ciphertext", "nonce"} <= columns.keys()
    assert {"plaintext", "credential", "password", "value"}.isdisjoint(columns)
    assert str(columns["ciphertext"]["type"]) == "BYTEA"
    assert str(columns["nonce"]["type"]) == "BYTEA"


def test_initial_migration_downgrades_and_reupgrades(
    alembic_config, database_engine
) -> None:
    command.downgrade(alembic_config, "base")
    try:
        assert CORE_TABLES.isdisjoint(inspect(database_engine).get_table_names())
    finally:
        command.upgrade(alembic_config, "head")
    assert CORE_TABLES <= set(inspect(database_engine).get_table_names())


def _job(target_id: str, status: JobStatus) -> AnalysisJob:
    return AnalysisJob(
        target_type=TargetType.GAME,
        canonical_target_id=target_id,
        canonical_url=f"https://store.steampowered.com/app/{target_id}",
        status=status,
    )


def _idempotency_record(key: str) -> IdempotencyRecord:
    return IdempotencyRecord(
        key=key,
        request_hash="a" * 64,
        method="POST",
        path="/api/v1/jobs/analysis",
        response_status=202,
        response_body={"id": str(UUID(int=0))},
    )
