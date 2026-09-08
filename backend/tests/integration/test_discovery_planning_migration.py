from uuid import uuid4
from alembic import command
from sqlalchemy import inspect, text


def test_current_0010_migration_preserves_activity_and_query(
    migrated_database, alembic_config, database_engine
):
    game_id, activity_id, query_id = (uuid4() for _ in range(3))
    try:
        command.downgrade(alembic_config, "20260908_0010")
        with database_engine.begin() as conn:
            conn.execute(
                text(
                    """INSERT INTO game_profiles
                (id,canonical_url,sort_name,current_facts,analysis,brief,source_status,model_metadata,prompt_metadata,favorite)
                VALUES (:id,'https://example.test/planning-migration','Game','{}','{}','{}','{}','{}','{}',false)"""
                ),
                {"id": game_id},
            )
            conn.execute(
                text(
                    "INSERT INTO activities(id,game_id,name) VALUES (:id,:game,'Preserved Activity')"
                ),
                {"id": activity_id, "game": game_id},
            )
            conn.execute(
                text(
                    'INSERT INTO discovery_queries(id,activity_id,source_snapshot) VALUES (:id,:activity,\'{"game":{"name":"Kept"}}\')'
                ),
                {"id": query_id, "activity": activity_id},
            )
            before = conn.scalar(
                text("SELECT to_jsonb(q) FROM discovery_queries q WHERE id=:id"),
                {"id": query_id},
            )
        command.upgrade(alembic_config, "head")
        assert "discovery_plans" in inspect(database_engine).get_table_names()
        with database_engine.begin() as conn:
            assert (
                conn.scalar(
                    text("SELECT to_jsonb(q) FROM discovery_queries q WHERE id=:id"),
                    {"id": query_id},
                )
                == before
            )
    finally:
        command.upgrade(alembic_config, "head")
        with database_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM discovery_queries WHERE id=:id"), {"id": query_id}
            )
            conn.execute(
                text("DELETE FROM activities WHERE id=:id"), {"id": activity_id}
            )
            conn.execute(
                text("DELETE FROM game_profiles WHERE id=:id"), {"id": game_id}
            )
