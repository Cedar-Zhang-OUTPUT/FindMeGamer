from uuid import uuid4
from alembic import command
from sqlalchemy import inspect, text


def test_current_0021_migration_preserves_existing_game_and_activity(
    migrated_database,
    alembic_config,
    database_engine,
):
    game_id, activity_id = uuid4(), uuid4()
    try:
        command.downgrade(alembic_config, "20260909_0021")
        with database_engine.begin() as conn:
            conn.execute(
                text(
                    """INSERT INTO game_profiles
                (id,canonical_url,sort_name,current_facts,analysis,brief,source_status,
                 model_metadata,prompt_metadata,favorite)
                VALUES (:id,'https://example.test/search-migration','Kept Game',
                        '{}','{}','{}','{}','{}','{}',false)"""
                ),
                {"id": game_id},
            )
            conn.execute(
                text(
                    "INSERT INTO activities(id,game_id,name) VALUES (:id,:game,'Kept Activity')"
                ),
                {"id": activity_id, "game": game_id},
            )
            before = conn.scalar(
                text("SELECT to_jsonb(a) FROM activities a WHERE id=:id"),
                {"id": activity_id},
            )
        command.upgrade(alembic_config, "head")
        assert {"creator_searches", "creator_search_units"}.issubset(
            inspect(database_engine).get_table_names()
        )
        with database_engine.begin() as conn:
            assert (
                conn.scalar(
                    text("SELECT to_jsonb(a) FROM activities a WHERE id=:id"),
                    {"id": activity_id},
                )
                == before
            )
            assert conn.scalar(text("SELECT count(*) FROM creator_searches")) == 0
            assert (
                conn.scalar(
                    text("SELECT count(*) FROM game_profiles WHERE id=:id"),
                    {"id": game_id},
                )
                == 1
            )
    finally:
        command.upgrade(alembic_config, "head")
        with database_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM activities WHERE id=:id"), {"id": activity_id}
            )
            conn.execute(
                text("DELETE FROM game_profiles WHERE id=:id"), {"id": game_id}
            )
