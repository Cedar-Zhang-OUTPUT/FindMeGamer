from contextlib import contextmanager
from decimal import Decimal
from threading import Event, Thread
from uuid import uuid4

from alembic import command
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.db.models.match import MatchTask
from app.db.models.profiles import CreatorProfile, GameProfile
from app.repositories.match import MatchRepository
from tests.integration.test_match_capacity import _seed_library


def test_0012_populated_library_and_match_survive_checkpoint_migration(
    migrated_database,
    alembic_config,
    database_engine,
):
    game_id, creator_ids, task_id = None, [], None
    try:
        command.downgrade(alembic_config, "20260914_native_0012")
        with Session(database_engine) as session:
            game, creator_ids = _seed_library(session, 2)
            game_id = game.id
            task = MatchRepository(session).create_locked_task(
                game.id, 5, Decimal("0.7")
            )
            task_id = task.id
            session.commit()
        with database_engine.connect() as connection:
            before = {
                table: connection.execute(
                    text(f"SELECT row_to_json(t) FROM {table} t ORDER BY id")
                )
                .scalars()
                .all()
                for table in (
                    "game_profiles",
                    "creator_profiles",
                    "match_tasks",
                    "match_candidate_inputs",
                    "match_screening_records",
                )
            }
        command.upgrade(alembic_config, "head")
        assert (
            "match_screening_checkpoints" in inspect(database_engine).get_table_names()
        )
        with database_engine.connect() as connection:
            for table, rows in before.items():
                assert (
                    connection.execute(
                        text(f"SELECT row_to_json(t) FROM {table} t ORDER BY id")
                    )
                    .scalars()
                    .all()
                    == rows
                )
            assert (
                connection.execute(
                    text("SELECT count(*) FROM match_screening_checkpoints")
                ).scalar_one()
                == 0
            )
    finally:
        command.upgrade(alembic_config, "head")
        with Session(database_engine) as session, session.begin():
            if task_id:
                session.delete(session.get(MatchTask, task_id))
                session.flush()
            if game_id:
                session.delete(session.get(GameProfile, game_id))
            for identifier in creator_ids:
                session.delete(session.get(CreatorProfile, identifier))


def test_duplicate_screening_delivery_does_not_call_provider_twice(
    migrated_database,
    database_engine,
    monkeypatch,
):
    from app.workers import match_tasks

    entered, release = Event(), Event()
    calls, errors = [], []

    @contextmanager
    def sessions():
        with Session(database_engine) as session:
            yield session

    @contextmanager
    def gateway():
        yield object()

    class BlockingScreening:
        def __init__(self, **kwargs):
            pass

        def run(self, task_id):
            calls.append(task_id)
            entered.set()
            assert release.wait(5)
            return []

    monkeypatch.setattr(match_tasks, "session_scope", sessions)
    monkeypatch.setattr(match_tasks, "_production_gateway", gateway)
    monkeypatch.setattr(match_tasks, "ScreeningService", BlockingScreening)
    task_id = uuid4()

    def run():
        try:
            match_tasks._ProductionScreening().run(task_id)
        except Exception as error:
            errors.append(error)

    first = Thread(target=run)
    first.start()
    try:
        assert entered.wait(3)
        second = Thread(target=run)
        second.start()
        second.join(1)
        assert not second.is_alive(), "Duplicate should defer to the existing owner."
        assert calls == [task_id]
    finally:
        release.set()
        first.join(5)
        if "second" in locals():
            second.join(5)
    assert errors == []
