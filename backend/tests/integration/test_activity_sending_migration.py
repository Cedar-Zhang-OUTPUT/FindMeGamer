from uuid import uuid4
import pytest
from alembic import command
from sqlalchemy import inspect, text


def test_0016_upgrade_preserves_drafting_records_and_refuses_sending_history_loss(
    migrated_database, alembic_config, database_engine
):
    game, activity, recipient_batch, template, composition, sending = [
        uuid4() for _ in range(6)
    ]
    try:
        command.downgrade(alembic_config, "20260908_0016")
        with database_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO game_profiles(id,canonical_url,sort_name,current_facts,analysis,brief,source_status,model_metadata,prompt_metadata) VALUES (:id,'https://example.test/sending-migration','Game','{}','{}','{}','{}','{}','{}')"
                ),
                {"id": game},
            )
            connection.execute(
                text(
                    "INSERT INTO activities(id,game_id,name) VALUES (:id,:game,'Activity')"
                ),
                {"id": activity, "game": game},
            )
            connection.execute(
                text(
                    "INSERT INTO activity_recipient_batches(id,activity_id,request_id,request_hash) VALUES (:id,:activity,:request,'fixture')"
                ),
                {"id": recipient_batch, "activity": activity, "request": uuid4()},
            )
            connection.execute(
                text(
                    "INSERT INTO outreach_template_versions(id,game_id,name,subject,fixed_fragments,fixed_hash,source_metadata) VALUES (:id,:game,'Template','Subject','[\"a\",\"b\",\"c\",\"d\",\"e\"]','fixture','{}')"
                ),
                {"id": template, "game": game},
            )
            connection.execute(
                text(
                    "INSERT INTO outreach_compositions(id,activity_id,recipient_batch_id,template_version_id,request_id,request_hash) VALUES (:id,:activity,:batch,:template,:request,'fixture')"
                ),
                {
                    "id": composition,
                    "activity": activity,
                    "batch": recipient_batch,
                    "template": template,
                    "request": uuid4(),
                },
            )
            before = connection.scalar(
                text("SELECT to_jsonb(c) FROM outreach_compositions c WHERE id=:id"),
                {"id": composition},
            )
            settings = (
                connection.execute(
                    text("SELECT to_jsonb(s) FROM shared_settings s ORDER BY id")
                )
                .scalars()
                .all()
            )
        command.upgrade(alembic_config, "head")
        with database_engine.begin() as connection:
            assert (
                connection.scalar(
                    text(
                        "SELECT to_jsonb(c) FROM outreach_compositions c WHERE id=:id"
                    ),
                    {"id": composition},
                )
                == before
            )
            assert (
                connection.execute(
                    text("SELECT to_jsonb(s) FROM shared_settings s ORDER BY id")
                )
                .scalars()
                .all()
                == settings
            )
            connection.execute(
                text(
                    "INSERT INTO activity_send_batches(id,activity_id,composition_id,request_id,request_hash,qualification_snapshot) VALUES (:id,:activity,:composition,:request,'fixture','{}')"
                ),
                {
                    "id": sending,
                    "activity": activity,
                    "composition": composition,
                    "request": uuid4(),
                },
            )
        with pytest.raises(RuntimeError, match="Back up"):
            command.downgrade(alembic_config, "20260908_0016")
        with database_engine.begin() as connection:
            assert (
                connection.scalar(
                    text(
                        "SELECT composition_id FROM activity_send_batches WHERE id=:id"
                    ),
                    {"id": sending},
                )
                == composition
            )
    finally:
        with database_engine.begin() as connection:
            if "activity_send_batches" in inspect(connection).get_table_names():
                connection.execute(
                    text("DELETE FROM activity_send_batches WHERE id=:id"),
                    {"id": sending},
                )
            for table, identity in (
                ("outreach_compositions", composition),
                ("outreach_template_versions", template),
                ("activity_recipient_batches", recipient_batch),
                ("activities", activity),
                ("game_profiles", game),
            ):
                connection.execute(
                    text(f"DELETE FROM {table} WHERE id=:id"), {"id": identity}
                )
        command.upgrade(alembic_config, "head")
