"""Maintenance-window upgrade preserves existing 0009 Library rows byte-for-byte."""

from uuid import uuid4

from alembic import command
from sqlalchemy import inspect, text


def test_0009_upgrade_preserves_library_and_adds_discovery_defaults(
    migrated_database, alembic_config, database_engine
):
    creator_id, game_id, activity_id, query_id = (uuid4() for _ in range(4))
    try:
        command.downgrade(alembic_config, "20260908_0009")
        with database_engine.begin() as conn:
            conn.execute(
                text(
                    """INSERT INTO creator_profiles
                (id,platform,platform_account_id,canonical_url,sort_name,current_facts,analysis,brief,
                source_status,model_metadata,prompt_metadata,favorite,manual_notes,manual_overrides)
                VALUES (:id,'x','109876543','https://x.com/i/user/109876543','Preserved',
                '{"followers": 42}','{"keep": true}','{}','{}','{}','{}',true,'Keep manual',
                '{"country":"JP"}')"""
                ),
                {"id": creator_id},
            )
            before = conn.scalar(
                text("SELECT to_jsonb(c) FROM creator_profiles c WHERE id=:id"),
                {"id": creator_id},
            )
        command.upgrade(alembic_config, "head")
        assert "discovery_attempts" in inspect(database_engine).get_table_names()
        with database_engine.begin() as conn:
            after = conn.scalar(
                text("SELECT to_jsonb(c) FROM creator_profiles c WHERE id=:id"),
                {"id": creator_id},
            )
            assert after == before
            conn.execute(
                text(
                    """INSERT INTO game_profiles
                (id,canonical_url,sort_name,current_facts,analysis,brief,source_status,model_metadata,prompt_metadata,favorite)
                VALUES (:id,'https://example.test/migration','Game','{}','{}','{}','{}','{}','{}',false)"""
                ),
                {"id": game_id},
            )
            conn.execute(
                text(
                    "INSERT INTO activities(id,game_id,name) VALUES (:id,:game,'Activity')"
                ),
                {"id": activity_id, "game": game_id},
            )
            conn.execute(
                text(
                    "INSERT INTO discovery_queries(id,activity_id) VALUES (:id,:activity)"
                ),
                {"id": query_id, "activity": activity_id},
            )
            query = conn.execute(
                text(
                    "SELECT conditions,source_snapshot,provider_states,status,result_count,stop_requested FROM discovery_queries WHERE id=:id"
                ),
                {"id": query_id},
            ).one()
            assert tuple(query) == ({}, {}, {}, "queued", 0, False)
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
            conn.execute(
                text("DELETE FROM creator_profiles WHERE id=:id"), {"id": creator_id}
            )
