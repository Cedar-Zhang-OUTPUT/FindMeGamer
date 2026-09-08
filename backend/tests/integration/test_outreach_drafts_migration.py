from uuid import uuid4
import pytest
from alembic import command
from sqlalchemy import inspect, text


def test_0015_upgrade_preserves_existing_game_and_settings_and_refuses_template_loss(
    migrated_database, alembic_config, database_engine
):
    game_id, template_id = uuid4(), uuid4()
    try:
        command.downgrade(alembic_config, "20260908_0015")
        with database_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO game_profiles(id,canonical_url,sort_name,current_facts,analysis,brief,source_status,model_metadata,prompt_metadata) VALUES (:id,'https://example.test/outreach-migration','Game','{}','{}','{}','{}','{}','{}')"
                ),
                {"id": game_id},
            )
            before = connection.scalar(
                text("SELECT to_jsonb(g) FROM game_profiles g WHERE id=:id"),
                {"id": game_id},
            )
            settings = (
                connection.execute(
                    text("SELECT to_jsonb(s) FROM shared_settings s ORDER BY id")
                )
                .scalars()
                .all()
            )
        command.upgrade(alembic_config, "head")
        assert {
            "outreach_template_versions",
            "outreach_compositions",
            "outreach_drafts",
        }.issubset(inspect(database_engine).get_table_names())
        with database_engine.begin() as connection:
            assert (
                connection.scalar(
                    text("SELECT to_jsonb(g) FROM game_profiles g WHERE id=:id"),
                    {"id": game_id},
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
                    "INSERT INTO outreach_template_versions(id,game_id,name,subject,fixed_fragments,fixed_hash,source_metadata) VALUES (:id,:game,'Template','Subject','[\"a\",\"b\",\"c\",\"d\",\"e\"]','fixture','{}')"
                ),
                {"id": template_id, "game": game_id},
            )
        with pytest.raises(RuntimeError, match="Back up"):
            command.downgrade(alembic_config, "20260908_0015")
        with database_engine.begin() as connection:
            assert (
                connection.scalar(
                    text("SELECT name FROM outreach_template_versions WHERE id=:id"),
                    {"id": template_id},
                )
                == "Template"
            )
    finally:
        with database_engine.begin() as connection:
            if "outreach_template_versions" in inspect(connection).get_table_names():
                connection.execute(
                    text("DELETE FROM outreach_template_versions WHERE id=:id"),
                    {"id": template_id},
                )
            connection.execute(
                text("DELETE FROM game_profiles WHERE id=:id"), {"id": game_id}
            )
        command.upgrade(alembic_config, "head")
