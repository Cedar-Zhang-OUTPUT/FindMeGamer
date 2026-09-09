from uuid import uuid4
from alembic import command
from sqlalchemy import text


def test_0019_upgrade_preserves_activity_game_and_recipient_snapshot(
    migrated_database, alembic_config, database_engine
):
    game, activity, batch, request = (uuid4() for _ in range(4))
    try:
        command.downgrade(alembic_config, "20260908_0019")
        with database_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO game_profiles(id,canonical_url,sort_name,current_facts,analysis,brief,source_status,model_metadata,prompt_metadata) VALUES (:id,'https://example.test/brief','Original game','{}','{}','{}','{}','{}','{}')"
                ),
                {"id": game},
            )
            conn.execute(
                text(
                    'INSERT INTO activities(id,game_id,name,source_snapshot) VALUES (:id,:game,\'Original activity\',\'{"game":{"name":"Original game"}}\')'
                ),
                {"id": activity, "game": game},
            )
            conn.execute(
                text(
                    "INSERT INTO activity_recipient_batches(id,activity_id,request_id,request_hash,source_snapshot) VALUES (:id,:activity,:request,'original-hash',CAST(:snapshot AS jsonb))"
                ),
                {"id": batch, "activity": activity, "request": request, "snapshot": '{"original":true}'},
            )
            before = conn.scalar(
                text(
                    "SELECT to_jsonb(b) FROM activity_recipient_batches b WHERE id=:id"
                ),
                {"id": batch},
            )
            source = conn.scalar(
                text("SELECT source_snapshot FROM activities WHERE id=:id"),
                {"id": activity},
            )
        command.upgrade(alembic_config, "head")
        with database_engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT campaign_brief,revision,source_snapshot FROM activities WHERE id=:id"
                ),
                {"id": activity},
            ).one()
            assert (
                row.campaign_brief is None
                and row.revision == 0
                and row.source_snapshot == source
            )
            assert (
                conn.scalar(
                    text(
                        "SELECT to_jsonb(b) FROM activity_recipient_batches b WHERE id=:id"
                    ),
                    {"id": batch},
                )
                == before
            )
            assert (
                conn.scalar(
                    text("SELECT sort_name FROM game_profiles WHERE id=:id"),
                    {"id": game},
                )
                == "Original game"
            )
    finally:
        command.upgrade(alembic_config, "head")
        with database_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM activity_recipient_batches WHERE id=:id"),
                {"id": batch},
            )
            conn.execute(text("DELETE FROM activities WHERE id=:id"), {"id": activity})
            conn.execute(text("DELETE FROM game_profiles WHERE id=:id"), {"id": game})
