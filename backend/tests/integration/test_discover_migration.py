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
            "discover_analysis_batches",
            "discover_analysis_items",
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


def test_batch_migration_preserves_discover_and_unique_match_link(
    migrated_database, database_engine, alembic_config
):
    try:
        command.downgrade(alembic_config, "20260914_native_0011")
        assert "discover_jobs" in inspect(database_engine).get_table_names()
        assert (
            "discover_analysis_batches"
            not in inspect(database_engine).get_table_names()
        )
        command.upgrade(alembic_config, "head")
        uniques = inspect(database_engine).get_unique_constraints(
            "discover_analysis_batches"
        )
        assert any(c["column_names"] == ["match_task_id"] for c in uniques)
        assert any(c["column_names"] == ["idempotency_key"] for c in uniques)
    finally:
        command.upgrade(alembic_config, "head")
