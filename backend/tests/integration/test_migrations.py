from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Event, Thread
from time import monotonic
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import event, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.enums import AnalysisStage, JobStatus, TargetType
from app.db.models.idempotency import IdempotencyRecord
from app.db.models.jobs import AnalysisJob, JOB_CHANGE_ADVISORY_LOCK_ID
from app.db.models.profiles import CreatorContact, CreatorProfile, GameProfile
from app.db.models.settings import SharedSettings
from app.repositories.jobs import JobsRepository
from app.workers.analysis_tasks import TerminalFailure, write_terminal_failure


CORE_TABLES = {
    "game_profiles",
    "creator_profiles",
    "creator_contacts",
    "analysis_jobs",
    "creator_analysis_nodes",
    "shared_settings",
    "service_secrets",
    "idempotency_records",
}


def test_initial_migration_creates_core_tables(database_inspector) -> None:
    names = set(database_inspector.get_table_names())
    assert CORE_TABLES <= names


def test_creator_contact_purpose_migrates_from_and_back_to_0006(
    migrated_database: None, alembic_config, database_engine
) -> None:
    try:
        command.downgrade(alembic_config, "20260904_0006")
        assert "purpose" not in {
            column["name"]
            for column in inspect(database_engine).get_columns("creator_contacts")
        }

        command.upgrade(alembic_config, "head")
        columns = {
            column["name"]: column
            for column in inspect(database_engine).get_columns("creator_contacts")
        }
        assert columns["purpose"]["nullable"] is True
        with database_engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260904_0007"
            )

        command.downgrade(alembic_config, "20260904_0006")
        assert "purpose" not in {
            column["name"]
            for column in inspect(database_engine).get_columns("creator_contacts")
        }
    finally:
        command.upgrade(alembic_config, "head")


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
        "stage": None,
        "completed_units": 0,
        "total_units": 0,
        "started_at": None,
    }
    if column == "stage":
        values.update(
            status="running",
            stage=value,
            total_units=5,
            started_at=datetime.now(UTC),
        )
    else:
        values[column] = value
    savepoint = session.begin_nested()
    try:
        with pytest.raises(IntegrityError) as error:
            session.execute(
                text(
                    """
                    INSERT INTO analysis_jobs (
                        id, target_type, canonical_target_id, canonical_url,
                        mode, status, stage, completed_units, total_units, started_at
                    ) VALUES (
                        :id, :target_type, :canonical_target_id, :canonical_url,
                        :mode, :status, :stage, :completed_units, :total_units,
                        :started_at
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
        assert tuple(repaired[:3]) == (0, 5, False)
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

        assert [tuple(row) for row in changed] == [(job_id, 4, 5, False)]
    finally:
        command.upgrade(alembic_config, "head")
        with database_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM analysis_jobs WHERE id = :job_id"),
                {"job_id": job_id},
            )


def test_runtime_job_mutation_and_public_state_migration_share_lock_order(
    migrated_database: None, alembic_config, database_engine
) -> None:
    job_id = uuid4()
    row_locked = Event()
    release_worker = Event()
    worker_pid: list[int] = []
    errors: list[BaseException] = []

    @contextmanager
    def worker_session_factory() -> Iterator[Session]:
        with Session(database_engine) as worker_session:
            worker_pid.append(worker_session.scalar(text("SELECT pg_backend_pid()")))
            yield worker_session

    def pause_after_worker_row_lock(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        normalized = " ".join(statement.casefold().split())
        if "analysis_jobs" in normalized and "for update" in normalized:
            row_locked.set()
            release_worker.wait(timeout=10)

    def mutate_job() -> None:
        try:
            write_terminal_failure(
                job_id,
                TerminalFailure(
                    code="analysis_internal_error",
                    message="Analysis failed unexpectedly. Please retry.",
                    retryable=True,
                ),
                session_factory=worker_session_factory,
                clock=lambda: datetime.now(UTC),
            )
        except BaseException as error:  # pragma: no branch - asserted below
            errors.append(error)

    def migrate() -> None:
        try:
            command.upgrade(alembic_config, "head")
        except BaseException as error:  # pragma: no branch - asserted below
            errors.append(error)

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
                            'create', 'queued', 0, 0, false
                    )
                    """
                ),
                {
                    "id": job_id,
                    "target_id": "2147483600",
                    "canonical_url": "https://store.steampowered.com/app/2147483600",
                },
            )

        event.listen(
            database_engine, "after_cursor_execute", pause_after_worker_row_lock
        )
        worker_thread = Thread(target=mutate_job, daemon=True)
        worker_thread.start()
        assert row_locked.wait(timeout=5)

        migration_thread = Thread(target=migrate, daemon=True)
        migration_thread.start()
        deadline = monotonic() + 5
        advisory_holder_pid = None
        while monotonic() < deadline and advisory_holder_pid is None:
            with database_engine.connect() as observation:
                advisory_holder_pid = observation.scalar(
                    text(
                        """
                        SELECT pid
                        FROM pg_locks
                        WHERE locktype = 'advisory'
                          AND granted
                          AND classid::bigint * 4294967296 + objid::bigint = :lock_id
                        ORDER BY pid
                        LIMIT 1
                        """
                    ),
                    {"lock_id": JOB_CHANGE_ADVISORY_LOCK_ID},
                )
            if advisory_holder_pid is None:
                row_locked.wait(timeout=0.01)
        assert advisory_holder_pid is not None
        assert worker_pid
        assert advisory_holder_pid == worker_pid[0]
        release_worker.set()
        worker_thread.join(timeout=10)
        migration_thread.join(timeout=10)

        assert not worker_thread.is_alive()
        assert not migration_thread.is_alive()
        assert errors == []
        with database_engine.connect() as verification:
            assert (
                verification.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260904_0007"
            )
    finally:
        release_worker.set()
        event.remove(
            database_engine, "after_cursor_execute", pause_after_worker_row_lock
        )
        command.upgrade(alembic_config, "head")
        with database_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM analysis_jobs WHERE id = :job_id"),
                {"job_id": job_id},
            )


def test_public_state_migration_does_not_deadlock_frozen_old_writer_order(
    migrated_database: None, alembic_config, database_engine
) -> None:
    job_id = uuid4()
    row_locked = Event()
    release_writer = Event()
    writer_errors: list[BaseException] = []
    migration_errors: list[BaseException] = []

    def frozen_old_writer() -> None:
        try:
            with Session(database_engine) as writer:
                job = writer.scalar(
                    select(AnalysisJob)
                    .where(AnalysisJob.id == job_id)
                    .with_for_update()
                )
                assert job is not None
                row_locked.set()
                release_writer.wait(timeout=10)
                job.status = JobStatus.FAILED
                job.error_code = "analysis_internal_error"
                job.error_message = "Analysis failed unexpectedly. Please retry."
                job.retryable = True
                job.completed_at = datetime.now(UTC)
                writer.flush()
                writer.commit()
        except BaseException as error:  # pragma: no branch - asserted below
            writer_errors.append(error)

    def migrate() -> None:
        try:
            command.upgrade(alembic_config, "head")
        except BaseException as error:  # pragma: no branch - asserted below
            migration_errors.append(error)

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
                        :id, 'game', '2147483599',
                        'https://store.steampowered.com/app/2147483599',
                        'create', 'queued', 0, 0, false
                    )
                    """
                ),
                {"id": job_id},
            )

        writer_thread = Thread(target=frozen_old_writer, daemon=True)
        writer_thread.start()
        assert row_locked.wait(timeout=5)

        migration_thread = Thread(target=migrate, daemon=True)
        migration_thread.start()
        migration_thread.join(timeout=5)
        assert not migration_thread.is_alive()
        assert len(migration_errors) == 1
        original = getattr(migration_errors[0], "orig", migration_errors[0])
        assert getattr(original, "sqlstate", None) == "55P03"

        release_writer.set()
        writer_thread.join(timeout=10)

        assert not writer_thread.is_alive()
        assert writer_errors == []
        command.upgrade(alembic_config, "head")
        with database_engine.connect() as verification:
            assert (
                verification.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260904_0007"
            )
            assert (
                verification.scalar(
                    text("SELECT status FROM analysis_jobs WHERE id = :job_id"),
                    {"job_id": job_id},
                )
                == "failed"
            )
    finally:
        release_writer.set()
        command.upgrade(alembic_config, "head")
        with database_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM analysis_jobs WHERE id = :job_id"),
                {"job_id": job_id},
            )


@pytest.mark.parametrize("actor", ["current-writer", "current-poller"])
def test_public_state_migration_rejects_advisory_only_inflight_activity(
    migrated_database: None, alembic_config, database_engine, actor: str
) -> None:
    advisory_acquired = Event()
    release_actor = Event()
    actor_errors: list[BaseException] = []

    def hold_advisory_only() -> None:
        try:
            with database_engine.connect() as connection:
                transaction = connection.begin()
                connection.execute(
                    text("SELECT pg_advisory_xact_lock(:lock_id)"),
                    {"lock_id": JOB_CHANGE_ADVISORY_LOCK_ID},
                )
                advisory_acquired.set()
                release_actor.wait(timeout=10)
                transaction.rollback()
        except BaseException as error:  # pragma: no branch - asserted below
            actor_errors.append(error)

    try:
        command.downgrade(alembic_config, "20260902_0003")
        actor_thread = Thread(target=hold_advisory_only, name=actor, daemon=True)
        actor_thread.start()
        assert advisory_acquired.wait(timeout=5)

        with pytest.raises(Exception) as error:
            command.upgrade(alembic_config, "head")
        original = getattr(error.value, "orig", error.value)
        assert getattr(original, "sqlstate", None) == "55P03"
        with database_engine.connect() as verification:
            assert (
                verification.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260902_0003"
            )

        release_actor.set()
        actor_thread.join(timeout=10)
        assert not actor_thread.is_alive()
        assert actor_errors == []
        command.upgrade(alembic_config, "head")
    finally:
        release_actor.set()
        command.upgrade(alembic_config, "head")


def test_public_state_migration_rejects_frozen_legacy_profile_mutation(
    migrated_database: None, alembic_config, database_engine
) -> None:
    profile_id, job_id = uuid4(), uuid4()
    profile_updated = Event()
    release_profile = Event()
    profile_errors: list[BaseException] = []
    migration_errors: list[BaseException] = []

    def mutate_profile() -> None:
        try:
            with database_engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        UPDATE game_profiles
                        SET canonical_url = 'https://evil.example/legacy-race'
                        WHERE id = :id
                        """
                    ),
                    {"id": profile_id},
                )
                profile_updated.set()
                release_profile.wait(timeout=10)
        except BaseException as error:  # pragma: no branch - asserted below
            profile_errors.append(error)

    def migrate() -> None:
        try:
            command.upgrade(alembic_config, "head")
        except BaseException as error:  # pragma: no branch - asserted below
            migration_errors.append(error)

    try:
        command.downgrade(alembic_config, "20260902_0003")
        with database_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO game_profiles (
                        id, steam_app_id, canonical_url, sort_name, current_facts,
                        analysis, brief, source_status, model_metadata, prompt_metadata
                    ) VALUES (
                        :profile_id, '734',
                        'https://store.steampowered.com/app/734', 'Legacy race',
                        '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                        '{}'::jsonb, '{}'::jsonb
                    );
                    """
                ),
                {"profile_id": profile_id},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO analysis_jobs (
                        id, target_type, canonical_target_id, canonical_url,
                        mode, status, stage, completed_units, total_units,
                        retryable, profile_id, result_payload,
                        started_at, completed_at
                    ) VALUES (
                        :job_id, 'game', '734',
                        'https://store.steampowered.com/app/734', 'create',
                        'succeeded', 'finalizing', 5, 5, false, :profile_id,
                        jsonb_build_object(
                            'profile_id', CAST(:profile_id_text AS text)
                        ), clock_timestamp(), clock_timestamp()
                    )
                    """
                ),
                {
                    "job_id": job_id,
                    "profile_id": profile_id,
                    "profile_id_text": str(profile_id),
                },
            )

        profile_thread = Thread(target=mutate_profile, daemon=True)
        profile_thread.start()
        assert profile_updated.wait(timeout=5)
        migration_thread = Thread(target=migrate, daemon=True)
        migration_thread.start()
        migration_thread.join(timeout=2)
        assert not migration_thread.is_alive()
        assert len(migration_errors) == 1
        original = getattr(migration_errors[0], "orig", migration_errors[0])
        assert getattr(original, "sqlstate", None) == "55P03"
        with database_engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260902_0003"
            )

        release_profile.set()
        profile_thread.join(timeout=10)
        assert not profile_thread.is_alive()
        assert profile_errors == []
        command.upgrade(alembic_config, "head")
        with database_engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT status FROM analysis_jobs WHERE id = :id"),
                    {"id": job_id},
                )
                == "failed"
            )
    finally:
        release_profile.set()
        if "profile_thread" in locals():
            profile_thread.join(timeout=10)
        if "migration_thread" in locals():
            migration_thread.join(timeout=10)
        command.downgrade(alembic_config, "20260902_0003")
        command.upgrade(alembic_config, "head")
        with database_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM analysis_jobs WHERE id = :id"), {"id": job_id}
            )
            connection.execute(
                text("DELETE FROM game_profiles WHERE id = :id"),
                {"id": profile_id},
            )


def test_public_state_downgrade_rejects_inflight_profile_mutation_and_retries(
    migrated_database: None, alembic_config, database_engine
) -> None:
    profile_id = uuid4()
    profile_updated = Event()
    release_profile = Event()
    profile_errors: list[BaseException] = []
    downgrade_errors: list[BaseException] = []

    def mutate_profile() -> None:
        try:
            with database_engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE creator_profiles SET manual_notes = 'in flight' "
                        "WHERE id = :id"
                    ),
                    {"id": profile_id},
                )
                profile_updated.set()
                release_profile.wait(timeout=10)
        except BaseException as error:  # pragma: no branch - asserted below
            profile_errors.append(error)

    def downgrade() -> None:
        try:
            command.downgrade(alembic_config, "20260902_0003")
        except BaseException as error:  # pragma: no branch - asserted below
            downgrade_errors.append(error)

    command.downgrade(alembic_config, "20260902_0004")
    with database_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO creator_profiles (
                    id, youtube_channel_id, canonical_url, sort_name,
                    current_facts, analysis, brief, source_status,
                    model_metadata, prompt_metadata
                ) VALUES (
                    :id, 'UCdowngrade123',
                    'https://www.youtube.com/channel/UCdowngrade123',
                    'Downgrade gate', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                    '{}'::jsonb, '{}'::jsonb, '{}'::jsonb
                )
                """
            ),
            {"id": profile_id},
        )

    profile_thread = Thread(target=mutate_profile, daemon=True)
    downgrade_thread = Thread(target=downgrade, daemon=True)
    try:
        profile_thread.start()
        assert profile_updated.wait(timeout=5)
        downgrade_thread.start()
        downgrade_thread.join(timeout=2)
        assert not downgrade_thread.is_alive()
        assert len(downgrade_errors) == 1
        original = getattr(downgrade_errors[0], "orig", downgrade_errors[0])
        assert getattr(original, "sqlstate", None) == "55P03"
        with database_engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260902_0004"
            )

        release_profile.set()
        profile_thread.join(timeout=10)
        assert not profile_thread.is_alive()
        assert profile_errors == []
        command.downgrade(alembic_config, "20260902_0003")
        command.upgrade(alembic_config, "head")
    finally:
        release_profile.set()
        profile_thread.join(timeout=10)
        downgrade_thread.join(timeout=10)
        command.upgrade(alembic_config, "head")
        with database_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM creator_profiles WHERE id = :id"),
                {"id": profile_id},
            )


def test_succeeded_profile_contract_lookup_has_partial_index(
    migrated_database: None, alembic_config, database_engine
) -> None:
    command.downgrade(alembic_config, "20260902_0003")
    try:
        command.upgrade(alembic_config, "head")
        indexes = {
            index["name"]: index
            for index in inspect(database_engine).get_indexes("analysis_jobs")
        }
        lookup_index = indexes["ix_analysis_jobs_succeeded_profile_id"]
        assert lookup_index["column_names"] == ["profile_id"]
        assert lookup_index["unique"] is False
        predicate = str(lookup_index["dialect_options"]["postgresql_where"])
        assert predicate == "((status)::text = 'succeeded'::text)"
    finally:
        command.upgrade(alembic_config, "head")


def test_public_state_migration_busy_gate_prevents_three_party_lock_cycle(
    migrated_database: None, alembic_config, database_engine
) -> None:
    job_id = uuid4()
    row_locked = Event()
    release_writer = Event()
    migration_done = Event()
    poll_advisory_acquired = Event()
    release_poll_after_advisory = Event()
    writer_errors: list[BaseException] = []
    migration_errors: list[BaseException] = []
    poll_errors: list[BaseException] = []
    poll_pid: list[int] = []

    def frozen_old_writer() -> None:
        try:
            with Session(database_engine) as writer:
                job = writer.scalar(
                    select(AnalysisJob)
                    .where(AnalysisJob.id == job_id)
                    .with_for_update()
                )
                assert job is not None
                row_locked.set()
                release_writer.wait(timeout=10)
                job.status = JobStatus.FAILED
                job.error_code = "analysis_internal_error"
                job.error_message = "Analysis failed unexpectedly. Please retry."
                job.retryable = True
                job.completed_at = datetime.now(UTC)
                writer.commit()
        except BaseException as error:  # pragma: no branch - asserted below
            writer_errors.append(error)

    def migrate() -> None:
        try:
            command.upgrade(alembic_config, "head")
        except BaseException as error:  # pragma: no branch - asserted below
            migration_errors.append(error)
        finally:
            migration_done.set()

    def poll() -> None:
        try:
            with Session(database_engine) as polling_session:
                poll_pid.append(polling_session.scalar(text("SELECT pg_backend_pid()")))
                connection = polling_session.connection()

                def pause_after_advisory(
                    _connection,
                    _cursor,
                    statement,
                    _parameters,
                    _context,
                    _executemany,
                ) -> None:
                    if "pg_advisory_xact_lock" in statement.casefold():
                        poll_advisory_acquired.set()
                        release_poll_after_advisory.wait(timeout=10)

                event.listen(connection, "after_cursor_execute", pause_after_advisory)
                try:
                    JobsRepository(polling_session).list_changed_jobs(
                        cursor=None,
                        status=None,
                        limit=100,
                    )
                finally:
                    event.remove(
                        connection, "after_cursor_execute", pause_after_advisory
                    )
                polling_session.commit()
        except BaseException as error:  # pragma: no branch - asserted below
            poll_errors.append(error)

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
                        :id, 'game', '2147483593',
                        'https://store.steampowered.com/app/2147483593',
                        'create', 'queued', 0, 0, false
                    )
                    """
                ),
                {"id": job_id},
            )

        writer_thread = Thread(target=frozen_old_writer, daemon=True)
        writer_thread.start()
        assert row_locked.wait(timeout=5)

        migration_thread = Thread(target=migrate, daemon=True)
        migration_thread.start()
        deadline = monotonic() + 5
        migration_waiting = False
        while monotonic() < deadline and not migration_done.is_set():
            with database_engine.connect() as observation:
                migration_waiting = bool(
                    observation.scalar(
                        text(
                            """
                            SELECT EXISTS (
                                SELECT 1
                                FROM pg_locks
                                WHERE locktype = 'relation'
                                  AND relation = 'analysis_jobs'::regclass
                                  AND mode = 'AccessExclusiveLock'
                                  AND NOT granted
                            )
                            """
                        )
                    )
                )
            if migration_waiting:
                break

        poll_thread = Thread(target=poll, daemon=True)
        poll_thread.start()
        assert poll_advisory_acquired.wait(timeout=5)
        release_poll_after_advisory.set()
        if migration_waiting:
            deadline = monotonic() + 5
            poll_waits_for_table = False
            while monotonic() < deadline and not poll_waits_for_table:
                if poll_pid:
                    with database_engine.connect() as observation:
                        poll_waits_for_table = bool(
                            observation.scalar(
                                text(
                                    """
                                    SELECT EXISTS (
                                        SELECT 1
                                        FROM pg_locks
                                        WHERE locktype = 'relation'
                                          AND pid = :pid
                                          AND relation = 'analysis_jobs'::regclass
                                          AND mode = 'AccessShareLock'
                                          AND NOT granted
                                    )
                                    """
                                ),
                                {"pid": poll_pid[0]},
                            )
                        )
            assert poll_waits_for_table
        release_writer.set()
        writer_thread.join(timeout=10)
        migration_thread.join(timeout=10)
        poll_thread.join(timeout=10)

        assert not writer_thread.is_alive()
        assert not migration_thread.is_alive()
        assert not poll_thread.is_alive()
        assert writer_errors == []
        assert poll_errors == []
        assert len(migration_errors) == 1
        original = getattr(migration_errors[0], "orig", migration_errors[0])
        assert getattr(original, "sqlstate", None) == "55P03"
        with database_engine.connect() as verification:
            assert (
                verification.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260902_0003"
            )
    finally:
        release_writer.set()
        release_poll_after_advisory.set()
        command.upgrade(alembic_config, "head")
        with database_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM analysis_jobs WHERE id = :job_id"),
                {"job_id": job_id},
            )


def test_public_state_migration_repairs_every_legacy_status_shape(
    migrated_database: None, alembic_config, database_engine
) -> None:
    job_ids = {
        status: uuid4() for status in ("queued", "running", "succeeded", "failed")
    }
    try:
        command.downgrade(alembic_config, "20260902_0003")
        with database_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO analysis_jobs (
                        id, target_type, canonical_target_id, canonical_url,
                        mode, status, stage, completed_units, total_units,
                        error_code, error_message, retryable, profile_id,
                        result_payload, started_at, completed_at
                    ) VALUES
                    (
                        :queued_id, 'game', '2147483595',
                        'https://store.steampowered.com/app/2147483595',
                        'create', 'queued', 'finalizing', 5, 5,
                        NULL, NULL, false, NULL, NULL,
                        clock_timestamp(), clock_timestamp()
                    ),
                    (
                        :running_id, 'game', '2147483596',
                        'https://store.steampowered.com/app/2147483596',
                        'create', 'running', NULL, 5, 5,
                        'steam_unavailable', 'unsafe legacy detail', true, NULL, NULL,
                        NULL, clock_timestamp()
                    ),
                    (
                        :succeeded_id, 'game', '2147483597',
                        'https://store.steampowered.com/app/2147483597',
                        'create', 'succeeded', NULL, 0, 5,
                        NULL, NULL, false, NULL, NULL,
                        NULL, NULL
                    ),
                    (
                        :failed_id, 'game', '2147483598',
                        'https://store.steampowered.com/app/2147483598',
                        'create', 'failed', 'analyzing', 9, 1,
                        'steam_unavailable', 'wrong public message', false, NULL, NULL,
                        NULL, NULL
                    )
                    """
                ),
                {f"{status}_id": job_id for status, job_id in job_ids.items()},
            )

        command.upgrade(alembic_config, "head")

        with database_engine.connect() as connection:
            rows = {
                row.id: row
                for row in connection.execute(
                    text(
                        """
                        SELECT id, status, stage, completed_units, total_units,
                               error_code, error_message, retryable, profile_id,
                               result_payload, started_at, completed_at
                        FROM analysis_jobs
                        WHERE id = ANY(:job_ids)
                        """
                    ),
                    {"job_ids": list(job_ids.values())},
                )
            }

        queued = rows[job_ids["queued"]]
        assert tuple(queued[1:]) == (
            "queued",
            None,
            0,
            0,
            None,
            None,
            False,
            None,
            None,
            None,
            None,
        )
        running = rows[job_ids["running"]]
        assert tuple(running[1:9]) == (
            "running",
            "fetching_data",
            4,
            5,
            None,
            None,
            False,
            None,
        )
        assert running.result_payload is None
        assert running.started_at is not None
        assert running.completed_at is None
        succeeded = rows[job_ids["succeeded"]]
        assert tuple(succeeded[1:9]) == (
            "failed",
            None,
            0,
            0,
            "analysis_job_result_invalid",
            "Analysis could not be completed for this target.",
            False,
            None,
        )
        assert succeeded.result_payload is None
        assert succeeded.started_at is None
        assert succeeded.completed_at is not None
        failed = rows[job_ids["failed"]]
        assert tuple(failed[1:9]) == (
            "failed",
            "analyzing",
            4,
            5,
            "steam_unavailable",
            "Analysis is temporarily unavailable. Please retry.",
            True,
            None,
        )
        assert failed.result_payload is None
        assert failed.started_at is not None
        assert failed.completed_at is not None
    finally:
        command.upgrade(alembic_config, "head")
        with database_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM analysis_jobs WHERE id = ANY(:job_ids)"),
                {"job_ids": list(job_ids.values())},
            )


def test_public_state_migration_normalizes_all_legacy_failed_errors(
    migrated_database: None, alembic_config, database_engine
) -> None:
    job_ids = [uuid4(), uuid4(), uuid4()]
    try:
        command.downgrade(alembic_config, "20260902_0003")
        with database_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO analysis_jobs (
                        id, target_type, canonical_target_id, canonical_url,
                        mode, status, error_code, error_message, retryable
                    ) VALUES
                    (:unknown, 'game', '2147483581',
                     'https://store.steampowered.com/app/2147483581',
                     'create', 'failed', 'legacy_unknown', 'unsafe detail', false),
                    (:missing, 'game', '2147483582',
                     'https://store.steampowered.com/app/2147483582',
                     'create', 'failed', NULL, NULL, false),
                    (:known, 'game', '2147483583',
                     'https://store.steampowered.com/app/2147483583',
                     'create', 'failed', 'steam_unavailable',
                     'wrong message', false)
                    """
                ),
                {
                    "unknown": job_ids[0],
                    "missing": job_ids[1],
                    "known": job_ids[2],
                },
            )

        command.upgrade(alembic_config, "head")
        with database_engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT id, error_code, error_message, retryable
                    FROM analysis_jobs WHERE id = ANY(:job_ids) ORDER BY id
                    """
                ),
                {"job_ids": job_ids},
            ).all()
        by_id = {row.id: tuple(row[1:]) for row in rows}
        assert by_id[job_ids[0]] == (
            "analysis_internal_error",
            "Analysis failed unexpectedly. Please retry.",
            True,
        )
        assert by_id[job_ids[1]] == by_id[job_ids[0]]
        assert by_id[job_ids[2]] == (
            "steam_unavailable",
            "Analysis is temporarily unavailable. Please retry.",
            True,
        )
    finally:
        command.upgrade(alembic_config, "head")
        with database_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM analysis_jobs WHERE id = ANY(:job_ids)"),
                {"job_ids": job_ids},
            )


def test_public_state_migration_repairs_invalid_succeeded_profile_contracts(
    migrated_database: None, alembic_config, database_engine
) -> None:
    game_profile_id, creator_profile_id = uuid4(), uuid4()
    job_ids = {
        name: uuid4() for name in ("game", "creator", "payload", "missing", "identity")
    }
    try:
        command.downgrade(alembic_config, "20260902_0003")
        with database_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO game_profiles (
                        id, steam_app_id, canonical_url, sort_name, current_facts,
                        analysis, brief, source_status, model_metadata, prompt_metadata
                    ) VALUES (
                        :id, '730', 'https://store.steampowered.com/app/730',
                        'Game', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                        '{}'::jsonb, '{}'::jsonb, '{}'::jsonb
                    )
                    """
                ),
                {"id": game_profile_id},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO creator_profiles (
                        id, youtube_channel_id, canonical_url, sort_name, current_facts,
                        analysis, brief, source_status, model_metadata, prompt_metadata
                    ) VALUES (
                        :creator_id, 'UCabcdef',
                        'https://www.youtube.com/channel/UCabcdef',
                        'Creator', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                        '{}'::jsonb, '{}'::jsonb, '{}'::jsonb
                    )
                    """
                ),
                {"creator_id": creator_profile_id},
            )
            rows = [
                (
                    job_ids["game"],
                    "game",
                    "730",
                    "https://store.steampowered.com/app/730",
                    game_profile_id,
                    game_profile_id,
                ),
                (
                    job_ids["creator"],
                    "creator",
                    "UCabcdef",
                    "https://www.youtube.com/channel/UCabcdef",
                    creator_profile_id,
                    creator_profile_id,
                ),
                (
                    job_ids["payload"],
                    "game",
                    "730",
                    "https://store.steampowered.com/app/730",
                    game_profile_id,
                    uuid4(),
                ),
                (
                    job_ids["missing"],
                    "game",
                    "730",
                    "https://store.steampowered.com/app/730",
                    uuid4(),
                    uuid4(),
                ),
                (
                    job_ids["identity"],
                    "game",
                    "440",
                    "https://store.steampowered.com/app/440",
                    game_profile_id,
                    game_profile_id,
                ),
            ]
            for (
                job_id,
                target_type,
                target_id,
                target_url,
                profile_id,
                payload_id,
            ) in rows:
                connection.execute(
                    text(
                        """
                        INSERT INTO analysis_jobs (
                            id, target_type, canonical_target_id, canonical_url,
                            mode, status, stage, completed_units, total_units,
                            retryable, profile_id, result_payload, started_at, completed_at
                        ) VALUES (
                            :id, :target_type, :target_id, :target_url,
                            'create', 'succeeded', 'finalizing', 5, 5, false,
                            :profile_id,
                            jsonb_build_object('profile_id', CAST(:payload_id AS text)),
                            clock_timestamp(), clock_timestamp()
                        )
                        """
                    ),
                    {
                        "id": job_id,
                        "target_type": target_type,
                        "target_id": target_id,
                        "target_url": target_url,
                        "profile_id": profile_id,
                        "payload_id": str(payload_id),
                    },
                )

        command.upgrade(alembic_config, "head")
        with database_engine.connect() as connection:
            statuses = dict(
                connection.execute(
                    text("SELECT id, status FROM analysis_jobs WHERE id = ANY(:ids)"),
                    {"ids": list(job_ids.values())},
                ).all()
            )
        assert statuses[job_ids["game"]] == "succeeded"
        assert statuses[job_ids["creator"]] == "succeeded"
        assert statuses[job_ids["payload"]] == "failed"
        assert statuses[job_ids["missing"]] == "failed"
        assert statuses[job_ids["identity"]] == "failed"
    finally:
        command.upgrade(alembic_config, "head")
        with database_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM analysis_jobs WHERE id = ANY(:ids)"),
                {"ids": list(job_ids.values())},
            )
            connection.execute(
                text("DELETE FROM game_profiles WHERE id = :id"),
                {"id": game_profile_id},
            )
            connection.execute(
                text("DELETE FROM creator_profiles WHERE id = :id"),
                {"id": creator_profile_id},
            )


def test_succeeded_result_payload_shape_is_enforced_by_postgresql(
    session: Session,
) -> None:
    profile = GameProfile(
        steam_app_id="731",
        canonical_url="https://store.steampowered.com/app/731",
        sort_name="Payload shape",
    )
    session.add(profile)
    session.flush()
    now = datetime.now(UTC)
    job = AnalysisJob(
        target_type=TargetType.GAME,
        canonical_target_id="731",
        canonical_url="https://store.steampowered.com/app/731",
        status=JobStatus.SUCCEEDED,
        stage=AnalysisStage.FINALIZING,
        completed_units=5,
        total_units=5,
        profile_id=profile.id,
        result_payload={"profile_id": str(profile.id)},
        started_at=now,
        completed_at=now,
    )
    session.add(job)
    session.flush()

    savepoint = session.begin_nested()
    try:
        with pytest.raises(IntegrityError) as error:
            session.execute(
                text(
                    """
                        UPDATE analysis_jobs
                        SET result_payload = jsonb_build_object(
                            'profile_id', CAST(:wrong_profile_id AS text)
                        )
                    WHERE id = :job_id
                    """
                ),
                {"job_id": job.id, "wrong_profile_id": str(uuid4())},
            )
        assert error.value.orig.diag.constraint_name == "ck_analysis_jobs_status_shape"
    finally:
        savepoint.rollback()


@pytest.mark.parametrize("mutation", ["update", "delete"])
def test_succeeded_profile_identity_is_continuously_enforced_by_postgresql(
    migrated_database: None, database_engine, mutation: str
) -> None:
    profile_id, job_id = uuid4(), uuid4()
    with database_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO game_profiles (
                    id, steam_app_id, canonical_url, sort_name, current_facts,
                    analysis, brief, source_status, model_metadata, prompt_metadata
                ) VALUES (
                    :profile_id, '732', 'https://store.steampowered.com/app/732',
                    'Continuous identity', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                    '{}'::jsonb, '{}'::jsonb, '{}'::jsonb
                )
                """
            ),
            {"profile_id": profile_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO analysis_jobs (
                    id, target_type, canonical_target_id, canonical_url,
                    mode, status, stage, completed_units, total_units,
                    retryable, profile_id, result_payload, started_at, completed_at
                ) VALUES (
                    :job_id, 'game', '732',
                    'https://store.steampowered.com/app/732', 'create',
                    'succeeded', 'finalizing', 5, 5, false, :profile_id,
                    jsonb_build_object(
                        'profile_id', CAST(:profile_id_text AS text)
                    ),
                    clock_timestamp(), clock_timestamp()
                )
                """
            ),
            {
                "profile_id": profile_id,
                "profile_id_text": str(profile_id),
                "job_id": job_id,
            },
        )

    try:
        with pytest.raises(IntegrityError):
            with database_engine.begin() as connection:
                if mutation == "update":
                    connection.execute(
                        text(
                            "UPDATE game_profiles SET canonical_url = "
                            "'https://evil.example/secret' WHERE id = :id"
                        ),
                        {"id": profile_id},
                    )
                else:
                    connection.execute(
                        text("DELETE FROM game_profiles WHERE id = :id"),
                        {"id": profile_id},
                    )
                connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    finally:
        with database_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM analysis_jobs WHERE id = :id"), {"id": job_id}
            )
            connection.execute(
                text("DELETE FROM game_profiles WHERE id = :id"), {"id": profile_id}
            )


def test_profile_delete_serializes_after_concurrent_legal_job_finalize(
    migrated_database: None, database_engine
) -> None:
    profile_id, job_id = uuid4(), uuid4()
    finalize_inserted = Event()
    release_finalize = Event()
    finalize_errors: list[BaseException] = []
    delete_errors: list[BaseException] = []
    delete_pid: list[int] = []
    with database_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO game_profiles (
                    id, steam_app_id, canonical_url, sort_name, current_facts,
                    analysis, brief, source_status, model_metadata, prompt_metadata
                ) VALUES (
                    :id, '733', 'https://store.steampowered.com/app/733',
                    'Concurrent identity', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                    '{}'::jsonb, '{}'::jsonb, '{}'::jsonb
                )
                """
            ),
            {"id": profile_id},
        )

    def finalize() -> None:
        try:
            with database_engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO analysis_jobs (
                            id, target_type, canonical_target_id, canonical_url,
                            mode, status, stage, completed_units, total_units,
                            retryable, profile_id, result_payload,
                            started_at, completed_at
                        ) VALUES (
                            :job_id, 'game', '733',
                            'https://store.steampowered.com/app/733', 'create',
                            'succeeded', 'finalizing', 5, 5, false, :profile_id,
                            jsonb_build_object(
                                'profile_id', CAST(:profile_id_text AS text)
                            ), clock_timestamp(), clock_timestamp()
                        )
                        """
                    ),
                    {
                        "job_id": job_id,
                        "profile_id": profile_id,
                        "profile_id_text": str(profile_id),
                    },
                )
                finalize_inserted.set()
                release_finalize.wait(timeout=10)
        except BaseException as error:  # pragma: no branch - asserted below
            finalize_errors.append(error)

    def delete_profile() -> None:
        try:
            with database_engine.begin() as connection:
                delete_pid.append(connection.scalar(text("SELECT pg_backend_pid()")))
                connection.execute(
                    text("DELETE FROM game_profiles WHERE id = :id"),
                    {"id": profile_id},
                )
        except BaseException as error:  # pragma: no branch - asserted below
            delete_errors.append(error)

    try:
        finalize_thread = Thread(target=finalize, daemon=True)
        finalize_thread.start()
        assert finalize_inserted.wait(timeout=5)
        delete_thread = Thread(target=delete_profile, daemon=True)
        delete_thread.start()
        deadline = monotonic() + 5
        delete_waiting = False
        while monotonic() < deadline and not delete_waiting:
            if delete_pid:
                with database_engine.connect() as observation:
                    delete_waiting = bool(
                        observation.scalar(
                            text(
                                """
                                SELECT EXISTS (
                                    SELECT 1 FROM pg_locks
                                    WHERE pid = :pid
                                      AND locktype = 'advisory'
                                      AND NOT granted
                                )
                                """
                            ),
                            {"pid": delete_pid[0]},
                        )
                    )
            finalize_inserted.wait(timeout=0.01)
        assert delete_waiting
        release_finalize.set()
        finalize_thread.join(timeout=10)
        delete_thread.join(timeout=10)

        assert not finalize_thread.is_alive()
        assert not delete_thread.is_alive()
        assert finalize_errors == []
        assert len(delete_errors) == 1
        original = getattr(delete_errors[0], "orig", delete_errors[0])
        assert getattr(original, "sqlstate", None) == "23514"
        with database_engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT status FROM analysis_jobs WHERE id = :id"),
                    {"id": job_id},
                )
                == "succeeded"
            )
    finally:
        release_finalize.set()
        with database_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM analysis_jobs WHERE id = :id"), {"id": job_id}
            )
            connection.execute(
                text("DELETE FROM game_profiles WHERE id = :id"), {"id": profile_id}
            )


def test_succeeded_profile_primary_key_change_cannot_orphan_job(
    migrated_database: None, database_engine
) -> None:
    profile_id, replacement_id, job_id = uuid4(), uuid4(), uuid4()
    with database_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO game_profiles (
                    id, steam_app_id, canonical_url, sort_name, current_facts,
                    analysis, brief, source_status, model_metadata, prompt_metadata
                ) VALUES (
                    :profile_id, '735',
                    'https://store.steampowered.com/app/735', 'PK identity',
                    '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                    '{}'::jsonb, '{}'::jsonb
                )
                """
            ),
            {"profile_id": profile_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO analysis_jobs (
                    id, target_type, canonical_target_id, canonical_url,
                    mode, status, stage, completed_units, total_units,
                    retryable, profile_id, result_payload,
                    started_at, completed_at
                ) VALUES (
                    :job_id, 'game', '735',
                    'https://store.steampowered.com/app/735', 'create',
                    'succeeded', 'finalizing', 5, 5, false, :profile_id,
                    jsonb_build_object(
                        'profile_id', CAST(:profile_id_text AS text)
                    ), clock_timestamp(), clock_timestamp()
                )
                """
            ),
            {
                "job_id": job_id,
                "profile_id": profile_id,
                "profile_id_text": str(profile_id),
            },
        )
    try:
        with pytest.raises(IntegrityError):
            with database_engine.begin() as connection:
                connection.execute(
                    text("UPDATE game_profiles SET id = :new_id WHERE id = :old_id"),
                    {"old_id": profile_id, "new_id": replacement_id},
                )
                connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    finally:
        with database_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM analysis_jobs WHERE id = :id"), {"id": job_id}
            )
            connection.execute(
                text("DELETE FROM game_profiles WHERE id IN (:old_id, :new_id)"),
                {"old_id": profile_id, "new_id": replacement_id},
            )


@pytest.mark.parametrize(
    "mutation",
    [
        "stage = 'finalizing', completed_units = 5, total_units = 5, "
        "started_at = clock_timestamp(), completed_at = clock_timestamp()",
        "status = 'running', stage = 'fetching_data', total_units = 5, "
        "started_at = clock_timestamp(), completed_at = clock_timestamp()",
        "status = 'succeeded', total_units = 5",
        "status = 'failed'",
        "updated_at = created_at - interval '1 day'",
    ],
)
def test_analysis_job_status_shape_is_enforced_by_postgresql(
    session: Session, mutation: str
) -> None:
    job = _job(f"invalid-status-shape-{uuid4()}", JobStatus.QUEUED)
    session.add(job)
    session.flush()
    savepoint = session.begin_nested()
    try:
        with pytest.raises(IntegrityError) as error:
            session.execute(
                text(f"UPDATE analysis_jobs SET {mutation} WHERE id = :job_id"),
                {"job_id": job.id},
            )
        assert error.value.orig.diag.constraint_name == (
            "ck_analysis_jobs_status_shape"
        )
    finally:
        savepoint.rollback()


def test_alembic_metadata_has_no_pending_schema_operations(
    migrated_database: None, alembic_config
) -> None:
    command.check(alembic_config)


def test_public_state_migration_repairs_future_created_legacy_job_timestamp(
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
                        mode, status, completed_units, total_units, retryable,
                        created_at, updated_at
                    ) VALUES (
                        :id, 'game', '2147483594',
                        'https://store.steampowered.com/app/2147483594',
                        'create', 'queued', 0, 0, false,
                        clock_timestamp() + interval '1 day', clock_timestamp()
                    )
                    """
                ),
                {"id": job_id},
            )

        command.upgrade(alembic_config, "head")

        with database_engine.connect() as connection:
            created_at, updated_at = connection.execute(
                text(
                    """
                    SELECT created_at, updated_at
                    FROM analysis_jobs
                    WHERE id = :job_id
                    """
                ),
                {"job_id": job_id},
            ).one()
        assert updated_at >= created_at
    finally:
        command.upgrade(alembic_config, "head")
        with database_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM analysis_jobs WHERE id = :job_id"),
                {"job_id": job_id},
            )


def _job(target_id: str, status: JobStatus) -> AnalysisJob:
    profile_id = uuid4() if status is JobStatus.SUCCEEDED else None
    terminal_timestamp = datetime.now(UTC) + timedelta(seconds=1)
    return AnalysisJob(
        target_type=TargetType.GAME,
        canonical_target_id=target_id,
        canonical_url=f"https://store.steampowered.com/app/{target_id}",
        status=status,
        stage=(
            AnalysisStage.FINALIZING
            if status is JobStatus.SUCCEEDED
            else (AnalysisStage.FETCHING_DATA if status is JobStatus.RUNNING else None)
        ),
        completed_units=5 if status is JobStatus.SUCCEEDED else 0,
        total_units=(5 if status in (JobStatus.RUNNING, JobStatus.SUCCEEDED) else 0),
        error_code=("analysis_internal_error" if status is JobStatus.FAILED else None),
        error_message=(
            "Analysis failed unexpectedly. Please retry."
            if status is JobStatus.FAILED
            else None
        ),
        retryable=status is JobStatus.FAILED,
        profile_id=profile_id,
        result_payload=(
            {"profile_id": str(profile_id)} if profile_id is not None else None
        ),
        started_at=(
            terminal_timestamp
            if status in (JobStatus.RUNNING, JobStatus.SUCCEEDED)
            else None
        ),
        completed_at=(
            terminal_timestamp
            if status in (JobStatus.SUCCEEDED, JobStatus.FAILED)
            else None
        ),
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
