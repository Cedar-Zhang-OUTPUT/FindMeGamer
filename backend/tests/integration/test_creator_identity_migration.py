from uuid import uuid4

from alembic import command
from sqlalchemy import text


def test_native_0008_identity_upgrade_preserves_existing_data(
    migrated_database, alembic_config, database_engine
):
    profile_id, contact_id, job_id, game_id, match_id = [uuid4() for _ in range(5)]
    try:
        command.downgrade(alembic_config, "20260914_native_0008")
        with database_engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO game_profiles (id, steam_app_id, canonical_url, sort_name,
                current_facts, analysis, brief, source_status, model_metadata,
                prompt_metadata, manual_overrides, profile_revision)
                VALUES (:id, '700700700', 'https://store.steampowered.com/app/700700700',
                'Preserved Game', '{"name":"Preserved Game"}', '{}', '{"frozen":"game"}',
                '{}', '{}', '{}', '{"facts.name":"Human Game"}', 4)
            """), {"id": game_id})
            connection.execute(text("""
                INSERT INTO match_tasks (id, game_id, locked_game_brief, locked_game_context,
                shuffle_seed, recommended_match_threshold, status, stage, completed_units,
                total_units, result_count, retryable, input_expires_at, started_at, completed_at)
                VALUES (:id, :game, '{"frozen":"game"}', '{"profile_revision": 4,"name":"Human Game"}',
                17, 0.7, 'succeeded', 'ranking', 0, 0, 0, false, now()+interval '1 day', now(), now())
            """), {"id": match_id, "game": game_id})
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
                    ("game_profiles", game_id),
                    ("match_tasks", match_id),
                ]
            }
        command.upgrade(alembic_config, "head")
        with database_engine.connect() as connection:
            for table, identifier in [
                ("creator_profiles", profile_id),
                ("creator_contacts", contact_id),
                ("analysis_jobs", job_id),
                ("game_profiles", game_id),
                ("match_tasks", match_id),
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
            connection.execute(text("DELETE FROM match_tasks WHERE id=:id"), {"id": match_id})
            connection.execute(text("DELETE FROM game_profiles WHERE id=:id"), {"id": game_id})
            connection.execute(
                text("DELETE FROM analysis_jobs WHERE id=:id"), {"id": job_id}
            )
            connection.execute(
                text("DELETE FROM creator_profiles WHERE id=:id"), {"id": profile_id}
            )
