from uuid import uuid4

from alembic import command
from sqlalchemy import text


def test_native_0008_identity_upgrade_preserves_existing_data(
    migrated_database, alembic_config, database_engine
):
    profile_id, contact_id, job_id = uuid4(), uuid4(), uuid4()
    try:
        command.downgrade(alembic_config, "20260914_native_0008")
        with database_engine.begin() as connection:
            connection.execute(
                text(
                    """INSERT INTO creator_profiles (id, youtube_channel_id, canonical_url, sort_name, current_facts, analysis, brief, source_status, model_metadata, prompt_metadata, manual_overrides, profile_revision)
                VALUES (:id, 'UCidentitymigration', 'https://www.youtube.com/channel/UCidentitymigration', 'Original', '{"title":"Original"}', '{}', '{}', '{}', '{}', '{}', '{"facts.title":"Human"}', 3)"""
                ),
                {"id": profile_id},
            )
            connection.execute(
                text(
                    """INSERT INTO creator_contacts (id, creator_id, email, source_type, is_manual, is_active) VALUES (:id, :creator, 'test@example.com', 'manual', true, true)"""
                ),
                {"id": contact_id, "creator": profile_id},
            )
            connection.execute(
                text(
                    """INSERT INTO analysis_jobs (id, target_type, canonical_target_id, canonical_url, mode, status, stage, completed_units, total_units, profile_id, result_payload, created_at, started_at, completed_at) VALUES (:id, 'creator', 'UCidentitymigration', 'https://www.youtube.com/channel/UCidentitymigration', 'create', 'succeeded', 'finalizing', 1, 1, :profile, jsonb_build_object('profile_id', CAST(:profile AS text)), now(), now(), now())"""
                ),
                {"id": job_id, "profile": profile_id},
            )
            before = {
                table: dict(
                    connection.execute(
                        text(f"SELECT * FROM {table} WHERE id=:id"), {"id": identifier}
                    )
                    .mappings()
                    .one()
                )
                for table, identifier in [
                    ("creator_profiles", profile_id),
                    ("creator_contacts", contact_id),
                    ("analysis_jobs", job_id),
                ]
            }
        command.upgrade(alembic_config, "head")
        with database_engine.connect() as connection:
            for table, identifier in [
                ("creator_profiles", profile_id),
                ("creator_contacts", contact_id),
                ("analysis_jobs", job_id),
            ]:
                after = dict(
                    connection.execute(
                        text(f"SELECT * FROM {table} WHERE id=:id"), {"id": identifier}
                    )
                    .mappings()
                    .one()
                )
                if table == "creator_profiles":
                    assert after.pop("platform") == "youtube"
                    assert after.pop("platform_account_id") == "UCidentitymigration"
                assert after == before[table]
    finally:
        command.upgrade(alembic_config, "head")
        with database_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM analysis_jobs WHERE id=:id"), {"id": job_id}
            )
            connection.execute(
                text("DELETE FROM creator_profiles WHERE id=:id"), {"id": profile_id}
            )
