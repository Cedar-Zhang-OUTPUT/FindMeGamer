from alembic import command
from sqlalchemy import inspect


def test_native_discover_upgrade_and_downgrade(
    migrated_database, database_engine, alembic_config
):
    try:
        command.downgrade(alembic_config, "20260914_native_0010")
        assert "discover_jobs" not in inspect(database_engine).get_table_names()
        command.upgrade(alembic_config, "head")
        tables = inspect(database_engine).get_table_names()
        assert {
            "discover_jobs",
            "discover_candidates",
            "game_profiles",
            "creator_profiles",
        } <= set(tables)
        columns = {
            c["name"] for c in inspect(database_engine).get_columns("discover_jobs")
        }
        assert {
            "lease_token",
            "lease_until",
            "game_job_id",
            "game_snapshot",
            "game_dispatched_at",
        } <= columns
        uniques = inspect(database_engine).get_unique_constraints("discover_candidates")
        assert any(
            c["column_names"] == ["discover_id", "platform", "platform_account_id"]
            for c in uniques
        )
    finally:
        command.upgrade(alembic_config, "head")
