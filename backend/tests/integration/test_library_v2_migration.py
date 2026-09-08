from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import inspect, text


def test_upgrade_from_current_release_preserves_source_and_new_manual_data(
    migrated_database,
    alembic_config,
    database_engine,
):
    old_id, first_id, second_id = uuid4(), uuid4(), uuid4()
    try:
        command.downgrade(alembic_config, "20260904_0007")
        with database_engine.begin() as connection:
            connection.execute(
                text(
                    """INSERT INTO game_profiles
                (id, steam_app_id, canonical_url, sort_name, current_facts, analysis, brief,
                 source_status, model_metadata, prompt_metadata, favorite)
                VALUES (:id, '8888', 'https://store.steampowered.com/app/8888', 'Existing',
                '{"name":"Existing"}'::jsonb, '{"keep": true}'::jsonb, '{}'::jsonb,
                '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, true)"""
                ),
                {"id": old_id},
            )
        command.upgrade(alembic_config, "head")
        with database_engine.begin() as connection:
            old = (
                connection.execute(
                    text("SELECT * FROM game_profiles WHERE id=:id"), {"id": old_id}
                )
                .mappings()
                .one()
            )
            assert old["steam_app_id"] == "8888" and old["analysis"] == {"keep": True}
            assert old["favorite"] is True and old["manual_overrides"] == {}
            assert old["reference_works"] == [] and old["manual_revision"] == 0
            for game_id in (first_id, second_id):
                connection.execute(
                    text(
                        """INSERT INTO game_profiles
                    (id, steam_app_id, canonical_url, sort_name, current_facts, analysis, brief,
                    source_status, model_metadata, prompt_metadata, favorite, manual_overrides)
                    VALUES (:id, NULL, '', 'Manual', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                    '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, false, '{"name":"Manual"}'::jsonb)"""
                    ),
                    {"id": game_id},
                )
        with pytest.raises(RuntimeError, match="manual game data exists"):
            command.downgrade(alembic_config, "20260904_0007")
        with database_engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM game_profiles WHERE id IN (:a,:b,:c)"),
                    {"a": old_id, "b": first_id, "c": second_id},
                )
                == 3
            )
        assert "manual_overrides" in {
            c["name"] for c in inspect(database_engine).get_columns("game_profiles")
        }
    finally:
        with database_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM game_profiles WHERE id IN (:a,:b,:c)"),
                {"a": old_id, "b": first_id, "c": second_id},
            )
        command.upgrade(alembic_config, "head")
