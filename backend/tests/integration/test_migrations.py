def test_initial_migration_creates_core_tables(database_inspector) -> None:
    names = set(database_inspector.get_table_names())
    assert {
        "game_profiles",
        "creator_profiles",
        "creator_contacts",
        "analysis_jobs",
        "shared_settings",
        "service_secrets",
        "idempotency_records",
    } <= names
