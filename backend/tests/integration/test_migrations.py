from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.enums import JobStatus, TargetType
from app.db.models.idempotency import IdempotencyRecord
from app.db.models.jobs import AnalysisJob
from app.db.models.profiles import CreatorContact, CreatorProfile, GameProfile
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


def test_only_one_active_manual_contact_exists_per_creator(session: Session) -> None:
    creator = CreatorProfile(
        youtube_channel_id=f"manual-constraint-{uuid4()}",
        canonical_url="https://youtube.com/channel/manual-constraint",
        sort_name="Manual Constraint",
    )
    session.add(creator)
    session.flush()
    session.add(
        CreatorContact(
            creator_id=creator.id,
            email="first@example.com",
            source_type="manual",
            is_manual=True,
            is_active=True,
        )
    )
    session.flush()

    savepoint = session.begin_nested()
    try:
        session.add(
            CreatorContact(
                creator_id=creator.id,
                email="second@example.com",
                source_type="manual",
                is_manual=True,
                is_active=True,
            )
        )
        with pytest.raises(IntegrityError) as error:
            session.flush()
        assert (
            error.value.orig.diag.constraint_name == "uq_creator_contacts_active_manual"
        )
    finally:
        savepoint.rollback()


def test_active_manual_migration_deduplicates_legacy_rows_and_downgrades_cleanly(
    migrated_database: None, alembic_config, database_engine
) -> None:
    creator_id = uuid4()
    older_contact_id = uuid4()
    newest_contact_id = uuid4()
    try:
        command.downgrade(alembic_config, "20260902_0001")
        with database_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO creator_profiles (
                        id, youtube_channel_id, canonical_url, sort_name,
                        current_facts, analysis, brief, source_status,
                        model_metadata, prompt_metadata
                    ) VALUES (
                        :id, :channel_id, :canonical_url, :sort_name,
                        '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                        '{}'::jsonb, '{}'::jsonb
                    )
                    """
                ),
                {
                    "id": creator_id,
                    "channel_id": f"legacy-manual-{creator_id}",
                    "canonical_url": f"https://youtube.com/channel/{creator_id}",
                    "sort_name": "Legacy Manual",
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO creator_contacts (
                        id, creator_id, email, source_type, is_manual,
                        is_active, created_at, updated_at
                    ) VALUES
                        (
                            :older_id, :creator_id, 'older@example.com',
                            'manual', true, true,
                            '2026-01-01T00:00:00Z', '2026-01-02T00:00:00Z'
                        ),
                        (
                            :newest_id, :creator_id, 'newest@example.com',
                            'manual', true, true,
                            '2026-02-01T00:00:00Z', '2026-02-02T00:00:00Z'
                        )
                    """
                ),
                {
                    "older_id": older_contact_id,
                    "newest_id": newest_contact_id,
                    "creator_id": creator_id,
                },
            )

        command.upgrade(alembic_config, "20260902_0002")
        with database_engine.connect() as connection:
            contacts = connection.execute(
                text(
                    """
                    SELECT id, is_active
                    FROM creator_contacts
                    WHERE creator_id = :creator_id
                    ORDER BY id
                    """
                ),
                {"creator_id": creator_id},
            ).all()
        assert {row.id: row.is_active for row in contacts} == {
            older_contact_id: False,
            newest_contact_id: True,
        }
        indexes = {
            index["name"]: index
            for index in inspect(database_engine).get_indexes("creator_contacts")
        }
        assert indexes["uq_creator_contacts_active_manual"]["unique"] is True

        command.downgrade(alembic_config, "20260902_0001")
        index_names = {
            index["name"]
            for index in inspect(database_engine).get_indexes("creator_contacts")
        }
        assert "uq_creator_contacts_active_manual" not in index_names
        with database_engine.connect() as connection:
            preserved = connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM creator_contacts
                    WHERE creator_id = :creator_id
                    """
                ),
                {"creator_id": creator_id},
            )
        assert preserved == 2
    finally:
        command.upgrade(alembic_config, "head")
        with database_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM creator_profiles WHERE id = :creator_id"),
                {"creator_id": creator_id},
            )


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


def test_analysis_job_watermark_is_owned_by_sqlalchemy_metadata() -> None:
    table = Base.metadata.tables["analysis_job_change_watermark"]

    assert set(table.columns.keys()) == {"singleton", "last_changed_at"}
    assert table.c.singleton.primary_key is True
    assert table.c.last_changed_at.nullable is False


@pytest.mark.parametrize(
    ("completed_units", "total_units", "status", "retryable"),
    [
        (-1, 0, "queued", False),
        (0, -1, "queued", False),
        (6, 5, "running", False),
        (0, 5, "running", True),
        (5, 5, "succeeded", True),
    ],
)
def test_analysis_job_public_state_is_enforced_by_postgresql(
    session: Session,
    completed_units: int,
    total_units: int,
    status: str,
    retryable: bool,
) -> None:
    job = _job(f"invalid-public-state-{uuid4()}", JobStatus.QUEUED)
    session.add(job)
    session.flush()
    savepoint = session.begin_nested()
    try:
        with pytest.raises(IntegrityError):
            session.execute(
                text(
                    """
                    UPDATE analysis_jobs
                    SET completed_units = :completed_units,
                        total_units = :total_units,
                        status = :status,
                        retryable = :retryable
                    WHERE id = :job_id
                    """
                ),
                {
                    "job_id": job.id,
                    "completed_units": completed_units,
                    "total_units": total_units,
                    "status": status,
                    "retryable": retryable,
                },
            )
    finally:
        savepoint.rollback()


def test_analysis_job_schema_upgrade_repairs_legacy_rows_and_adds_query_index(
    migrated_database: None, alembic_config, database_engine
) -> None:
    job_id = uuid4()
    try:
        command.downgrade(alembic_config, "20260902_0002")
        with database_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO analysis_jobs (
                        id, target_type, canonical_target_id, canonical_url,
                        mode, status, completed_units, total_units, retryable,
                        correlation_id
                    ) VALUES (
                        :id, 'game', :target_id, :canonical_url,
                        'create', 'running', -9, -1, true,
                        'api-key=legacy-secret'
                    )
                    """
                ),
                {
                    "id": job_id,
                    "target_id": f"legacy-job-{job_id}",
                    "canonical_url": f"https://store.steampowered.com/app/{job_id}",
                },
            )
            legacy_updated_at = connection.scalar(
                text("SELECT updated_at FROM analysis_jobs WHERE id = :job_id"),
                {"job_id": job_id},
            )

        command.upgrade(alembic_config, "head")

        with database_engine.connect() as connection:
            repaired = connection.execute(
                text(
                    """
                    SELECT completed_units, total_units, retryable, updated_at
                    FROM analysis_jobs
                    WHERE id = :job_id
                    """
                ),
                {"job_id": job_id},
            ).one()
            watermark = connection.scalar(
                text(
                    "SELECT last_changed_at FROM analysis_job_change_watermark "
                    "WHERE singleton"
                )
            )
        assert tuple(repaired[:3]) == (0, 0, False)
        assert repaired.updated_at > legacy_updated_at
        assert watermark >= repaired.updated_at

        inspector = inspect(database_engine)
        constraint_names = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("analysis_jobs")
        }
        assert {
            "ck_analysis_jobs_completed_units_nonnegative",
            "ck_analysis_jobs_total_units_nonnegative",
            "ck_analysis_jobs_completed_not_above_total",
            "ck_analysis_jobs_retryable_only_failed",
        } <= constraint_names
        indexes = {
            index["name"]: index for index in inspector.get_indexes("analysis_jobs")
        }
        assert indexes["ix_analysis_jobs_updated_at_id"]["column_names"] == [
            "updated_at",
            "id",
        ]
        assert indexes["ix_analysis_jobs_updated_at_id"]["unique"] is False
    finally:
        command.upgrade(alembic_config, "head")
        with database_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM analysis_jobs WHERE id = :job_id"),
                {"job_id": job_id},
            )


def test_analysis_job_schema_upgrade_handles_empty_database_and_reupgrade(
    migrated_database: None, alembic_config, database_engine
) -> None:
    command.downgrade(alembic_config, "20260902_0002")
    try:
        with database_engine.begin() as connection:
            connection.execute(text("DELETE FROM analysis_jobs"))

        command.upgrade(alembic_config, "head")
        command.upgrade(alembic_config, "head")

        with database_engine.connect() as connection:
            watermark_count = connection.scalar(
                text("SELECT count(*) FROM analysis_job_change_watermark")
            )
        assert watermark_count == 1
        indexes = {
            index["name"]: index
            for index in inspect(database_engine).get_indexes("analysis_jobs")
        }
        assert indexes["ix_analysis_jobs_updated_at_id"]["column_names"] == [
            "updated_at",
            "id",
        ]
    finally:
        command.upgrade(alembic_config, "head")


def test_public_state_repair_is_visible_after_a_preupgrade_cursor(
    migrated_database: None, alembic_config, database_engine
) -> None:
    job_id = uuid4()
    try:
        command.downgrade(alembic_config, "20260902_0003")
        with database_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO analysis_jobs (
                        id, target_type, canonical_target_id, canonical_url,
                        mode, status, completed_units, total_units, retryable
                    ) VALUES (
                        :id, 'game', :target_id, :canonical_url,
                        'create', 'running', 9, 1, true
                    )
                    """
                ),
                {
                    "id": job_id,
                    "target_id": f"cursor-visible-repair-{job_id}",
                    "canonical_url": f"https://store.steampowered.com/app/{job_id}",
                },
            )
            cursor_timestamp = connection.scalar(
                text("SELECT updated_at FROM analysis_jobs WHERE id = :job_id"),
                {"job_id": job_id},
            )

        command.upgrade(alembic_config, "head")

        with database_engine.connect() as connection:
            changed = connection.execute(
                text(
                    """
                    SELECT id, completed_units, total_units, retryable
                    FROM analysis_jobs
                    WHERE (updated_at, id) > (:cursor_timestamp, :cursor_id)
                      AND id = :job_id
                    """
                ),
                {
                    "cursor_timestamp": cursor_timestamp,
                    "cursor_id": job_id,
                    "job_id": job_id,
                },
            ).all()

        assert [tuple(row) for row in changed] == [(job_id, 1, 1, False)]
    finally:
        command.upgrade(alembic_config, "head")
        with database_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM analysis_jobs WHERE id = :job_id"),
                {"job_id": job_id},
            )


def test_alembic_metadata_has_no_pending_schema_operations(
    migrated_database: None, alembic_config
) -> None:
    command.check(alembic_config)


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
