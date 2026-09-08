from uuid import uuid4

from alembic import command
from sqlalchemy import inspect, text


def test_current_0011_migration_preserves_plan_and_query(
    migrated_database, alembic_config, database_engine
):
    game_id, activity_id, query_id, plan_id = (uuid4() for _ in range(4))
    try:
        command.downgrade(alembic_config, "20260908_0011")
        with database_engine.begin() as conn:
            conn.execute(
                text(
                    """INSERT INTO game_profiles
                (id,canonical_url,sort_name,current_facts,analysis,brief,source_status,model_metadata,prompt_metadata,favorite)
                VALUES (:id,'https://example.test/evaluation-migration','Game','{}','{}','{}','{}','{}','{}',false)"""
                ),
                {"id": game_id},
            )
            conn.execute(
                text(
                    "INSERT INTO activities(id,game_id,name) VALUES (:id,:game,'Kept')"
                ),
                {"id": activity_id, "game": game_id},
            )
            conn.execute(
                text(
                    "INSERT INTO discovery_queries(id,activity_id,source_snapshot) VALUES (:id,:activity,'{}')"
                ),
                {"id": query_id, "activity": activity_id},
            )
            conn.execute(
                text(
                    "INSERT INTO discovery_plans(id,activity_id,query_id,model,status) VALUES (:id,:activity,:query,'fixture','succeeded')"
                ),
                {"id": plan_id, "activity": activity_id, "query": query_id},
            )
            before = conn.scalar(
                text("SELECT to_jsonb(p) FROM discovery_plans p WHERE id=:id"),
                {"id": plan_id},
            )
        command.upgrade(alembic_config, "head")
        assert {
            "discovery_evaluation_runs",
            "discovery_evaluation_items",
            "discovery_evaluation_steps",
        }.issubset(inspect(database_engine).get_table_names())
        with database_engine.begin() as conn:
            assert (
                conn.scalar(
                    text("SELECT to_jsonb(p) FROM discovery_plans p WHERE id=:id"),
                    {"id": plan_id},
                )
                == before
            )
            assert (
                conn.scalar(
                    text("SELECT count(*) FROM discovery_queries WHERE id=:id"),
                    {"id": query_id},
                )
                == 1
            )
    finally:
        command.upgrade(alembic_config, "head")
        with database_engine.begin() as conn:
            for table, identity in (
                ("discovery_plans", plan_id),
                ("discovery_queries", query_id),
                ("activities", activity_id),
                ("game_profiles", game_id),
            ):
                conn.execute(
                    text(f"DELETE FROM {table} WHERE id=:id"), {"id": identity}
                )
