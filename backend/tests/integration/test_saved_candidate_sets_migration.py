from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import inspect, text


def test_0014_upgrade_preserves_query_and_populated_downgrade_refuses_loss(
    migrated_database, alembic_config, database_engine
):
    game_id, activity_id, query_id, saved_id = (uuid4() for _ in range(4))
    try:
        command.downgrade(alembic_config, "20260908_0014")
        with database_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO game_profiles(id,canonical_url,sort_name,current_facts,analysis,brief,source_status,model_metadata,prompt_metadata) VALUES (:id,'https://example.test/saved-migration','Game','{}','{}','{}','{}','{}','{}')"
                ),
                {"id": game_id},
            )
            connection.execute(
                text(
                    "INSERT INTO activities(id,game_id,name) VALUES (:id,:game,'Activity')"
                ),
                {"id": activity_id, "game": game_id},
            )
            connection.execute(
                text(
                    'INSERT INTO discovery_queries(id,activity_id,status,provider_states,result_count) VALUES (:id,:activity,\'paused\',\'{"youtube":{"cursor":{"token":"preserve"}}}\',4)'
                ),
                {"id": query_id, "activity": activity_id},
            )
            before = connection.scalar(
                text("SELECT to_jsonb(q) FROM discovery_queries q WHERE id=:id"),
                {"id": query_id},
            )
        command.upgrade(alembic_config, "head")
        assert "saved_candidate_sets" in inspect(database_engine).get_table_names()
        with database_engine.begin() as connection:
            assert (
                connection.scalar(
                    text("SELECT to_jsonb(q) FROM discovery_queries q WHERE id=:id"),
                    {"id": query_id},
                )
                == before
            )
            connection.execute(
                text(
                    "INSERT INTO saved_candidate_sets(id,query_id,request_id,request_hash,name,candidate_ids) VALUES (:id,:query,:request,'fixture','Saved','[]')"
                ),
                {"id": saved_id, "query": query_id, "request": uuid4()},
            )
        with pytest.raises(RuntimeError, match="Back up"):
            command.downgrade(alembic_config, "20260908_0014")
        with database_engine.begin() as connection:
            assert (
                connection.scalar(
                    text("SELECT name FROM saved_candidate_sets WHERE id=:id"),
                    {"id": saved_id},
                )
                == "Saved"
            )
    finally:
        with database_engine.begin() as connection:
            if "saved_candidate_sets" in inspect(connection).get_table_names():
                connection.execute(
                    text("DELETE FROM saved_candidate_sets WHERE id=:id"),
                    {"id": saved_id},
                )
            connection.execute(
                text("DELETE FROM discovery_queries WHERE id=:id"), {"id": query_id}
            )
            connection.execute(
                text("DELETE FROM activities WHERE id=:id"), {"id": activity_id}
            )
            connection.execute(
                text("DELETE FROM game_profiles WHERE id=:id"), {"id": game_id}
            )
        command.upgrade(alembic_config, "head")
