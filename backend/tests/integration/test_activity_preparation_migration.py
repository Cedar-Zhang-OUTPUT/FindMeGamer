from uuid import uuid4
from alembic import command
from sqlalchemy import inspect, text


def test_0012_upgrade_preserves_evaluation_and_activity(
    migrated_database, alembic_config, database_engine
):
    game_id, activity_id, query_id, run_id = (uuid4() for _ in range(4))
    try:
        command.downgrade(alembic_config, "20260908_0012")
        with database_engine.begin() as conn:
            conn.execute(
                text(
                    """INSERT INTO game_profiles
            (id,canonical_url,sort_name,current_facts,analysis,brief,source_status,model_metadata,prompt_metadata,favorite)
            VALUES (:id,'https://example.test/preparation-migration','Game','{}','{}','{}','{}','{}','{}',false)"""
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
                    "INSERT INTO discovery_queries(id,activity_id,source_snapshot) VALUES (:id,:activity,'{}')"
                ),
                {"id": query_id, "activity": activity_id},
            )
            conn.execute(
                text(
                    "INSERT INTO discovery_evaluation_runs(id,query_id,game_fingerprint,method_version,status) VALUES (:id,:query,'known','fixture','completed')"
                ),
                {"id": run_id, "query": query_id},
            )
            before = conn.scalar(
                text(
                    "SELECT to_jsonb(r) FROM discovery_evaluation_runs r WHERE id=:id"
                ),
                {"id": run_id},
            )
        command.upgrade(alembic_config, "head")
        assert {
            "activity_selections",
            "activity_recipient_batches",
            "activity_recipient_snapshots",
        }.issubset(inspect(database_engine).get_table_names())
        with database_engine.begin() as conn:
            assert (
                conn.scalar(
                    text(
                        "SELECT to_jsonb(r) FROM discovery_evaluation_runs r WHERE id=:id"
                    ),
                    {"id": run_id},
                )
                == before
            )
            assert (
                conn.scalar(
                    text("SELECT name FROM activities WHERE id=:id"),
                    {"id": activity_id},
                )
                == "Preserved Activity"
            )
    finally:
        command.upgrade(alembic_config, "head")
        with database_engine.begin() as conn:
            for table, identity in (
                ("discovery_evaluation_runs", run_id),
                ("discovery_queries", query_id),
                ("activities", activity_id),
                ("game_profiles", game_id),
            ):
                conn.execute(
                    text(f"DELETE FROM {table} WHERE id=:id"), {"id": identity}
                )
