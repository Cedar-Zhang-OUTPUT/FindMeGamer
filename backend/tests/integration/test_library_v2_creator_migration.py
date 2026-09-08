from uuid import uuid4
import json

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError


def test_database_historical_identity_requires_exact_profile_and_older_binding(session):
    from datetime import UTC, datetime
    from app.db.models.profiles import CreatorIdentityBinding
    from tests.integration.test_profiles_api import add_creator

    creator = add_creator(session, channel_id="UCmigration123", name="Original")
    creator.identity_revision = 1
    creator.platform = "x"
    creator.youtube_channel_id = None
    creator.canonical_url = "https://x.com/i/user/123"
    binding = CreatorIdentityBinding(
        creator_id=creator.id,
        revision=0,
        platform="youtube",
        account_id="UCmigration123",
        canonical_url="https://www.youtube.com/channel/UCmigration123",
        changed_at=datetime.now(UTC),
    )
    session.add(binding)
    session.flush()

    def valid(
        profile_id=creator.id, target_id="UCmigration123", url=binding.canonical_url
    ):
        return session.scalar(
            text(
                "SELECT analysis_job_succeeded_profile_is_valid('creator',:id,:target,:url)"
            ),
            {"id": profile_id, "target": target_id, "url": url},
        )

    assert valid() is True
    assert valid(profile_id=uuid4()) is False
    assert (
        valid(target_id="UCwrong123", url="https://www.youtube.com/channel/UCwrong123")
        is False
    )
    assert valid(url="https://youtube.com/channel/UCmigration123") is False
    binding.revision = 1
    session.flush()
    assert valid() is False
    binding.revision = 0
    binding.platform = "x"
    session.flush()
    assert valid() is False


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE creator_profiles SET identity_revision=1 WHERE id=:id",
        'UPDATE creator_profiles SET manual_overrides=\'{"name":"Edited"}\' WHERE id=:id',
        "INSERT INTO creator_identity_bindings (creator_id,revision,platform,account_id,canonical_url,changed_at) VALUES (:id,0,'youtube','guard-channel','https://youtube.com/channel/guard-channel',now())",
        "INSERT INTO creator_contacts (id,creator_id,email,source_type,is_manual,validation_state,priority,is_active,manual_overrides) VALUES (:contact,:id,'edited@example.com','manual',true,'unverified',0,true,'{\"purpose\":\"Edited\"}')",
    ],
)
def test_each_identity_or_manual_layer_blocks_lossy_downgrade(
    migrated_database, alembic_config, database_engine, mutation
):
    creator_id = uuid4()
    try:
        with database_engine.begin() as conn:
            conn.execute(
                text(
                    """INSERT INTO creator_profiles
                (id,youtube_channel_id,canonical_url,sort_name,current_facts,analysis,brief,
                source_status,model_metadata,prompt_metadata,favorite)
                VALUES (:id,'guard-channel','https://youtube.com/channel/guard-channel',
                'Guard','{}','{}','{}','{}','{}','{}',false)"""
                ),
                {"id": creator_id},
            )
            conn.execute(text(mutation), {"id": creator_id, "contact": uuid4()})
        with pytest.raises(RuntimeError, match="creator library data"):
            command.downgrade(alembic_config, "20260908_0008")
        with database_engine.connect() as conn:
            assert (
                conn.scalar(
                    text("SELECT count(*) FROM creator_profiles WHERE id=:id"),
                    {"id": creator_id},
                )
                == 1
            )
    finally:
        with database_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM creator_profiles WHERE id=:id"), {"id": creator_id}
            )
        command.upgrade(alembic_config, "head")


def test_creator_library_upgrade_preserves_contacts_and_guards_downgrade(
    migrated_database, alembic_config, database_engine
):
    creator_id, other_id, contact_id = uuid4(), uuid4(), uuid4()
    try:
        command.downgrade(alembic_config, "20260908_0008")
        with database_engine.begin() as conn:
            conn.execute(
                text(
                    """INSERT INTO creator_profiles
                (id,youtube_channel_id,canonical_url,sort_name,current_facts,analysis,brief,
                source_status,model_metadata,prompt_metadata,favorite,manual_notes)
                VALUES (:id,'migration-channel','https://youtube.com/channel/migration-channel',
                'Original','{"name":"Original"}','{"keep": true}','{}','{}','{}','{}',true,'Keep notes')"""
                ),
                {"id": creator_id},
            )
            conn.execute(
                text(
                    """INSERT INTO creator_contacts
                (id,creator_id,email,purpose,source_type,source_url,is_manual,validation_state,priority,is_active)
                VALUES (:id,:creator,'source@example.com','Business','youtube_about',
                'https://youtube.com/channel/migration-channel',false,'unverified',0,true)"""
                ),
                {"id": contact_id, "creator": creator_id},
            )
            conn.execute(
                text(
                    "UPDATE creator_profiles SET current_facts=CAST(:facts AS jsonb), last_analyzed_at='2026-09-08T01:00:00Z' WHERE id=:id"
                ),
                {
                    "id": creator_id,
                    "facts": json.dumps(
                        {
                            "name": "Original",
                            "representative_videos": [
                                {
                                    "id": "existing-video",
                                    "title": "Known work",
                                    "view_count": 12,
                                    "like_count": None,
                                },
                                {"id": "existing-video", "title": "Duplicate"},
                            ],
                        }
                    ),
                },
            )
        command.upgrade(alembic_config, "head")
        assert "creator_works" in inspect(database_engine).get_table_names()
        assert "creator_identity_bindings" in inspect(database_engine).get_table_names()
        with database_engine.begin() as conn:
            row = (
                conn.execute(
                    text("SELECT * FROM creator_profiles WHERE id=:id"),
                    {"id": creator_id},
                )
                .mappings()
                .one()
            )
            assert (
                row["platform"] == "youtube"
                and row["platform_account_id"] == "migration-channel"
            )
            assert (
                row["analysis"] == {"keep": True}
                and row["manual_notes"] == "Keep notes"
            )
            assert row["manual_overrides"] == {} and row["manual_revision"] == 0
            assert row["identity_revision"] == 0 and row["identity_changed_at"] is None
            contact = (
                conn.execute(
                    text("SELECT * FROM creator_contacts WHERE id=:id"),
                    {"id": contact_id},
                )
                .mappings()
                .one()
            )
            assert contact["is_manual"] is False and contact["manual_overrides"] == {}
            assert contact["identity_revision"] == 0
            work = (
                conn.execute(
                    text("SELECT * FROM creator_works WHERE creator_id=:id"),
                    {"id": creator_id},
                )
                .mappings()
                .one()
            )
            assert (
                work["source_content_id"] == "existing-video"
                and work["origin"] == "source"
            )
            assert work["source_fields"]["content_title"] == "Known work"
            assert work["source_fields"]["metrics"] == [{"name": "views", "value": 12}]
            assert work["source_fields"]["content_type"] == "unverified"
            assert contact["source_fields"] == {
                "email": "source@example.com",
                "purpose": "Business",
                "source_url": "https://youtube.com/channel/migration-channel",
                "validation_state": "unverified",
                "is_active": True,
            }
            for email in ("one@example.com", "two@example.com"):
                conn.execute(
                    text(
                        """INSERT INTO creator_contacts
                    (id,creator_id,email,source_type,is_manual,validation_state,priority,is_active)
                    VALUES (:id,:creator,:email,'manual',true,'unverified',0,true)"""
                    ),
                    {"id": uuid4(), "creator": creator_id, "email": email},
                )
            conn.execute(
                text(
                    """INSERT INTO creator_profiles
                (id,platform,platform_account_id,canonical_url,sort_name,current_facts,analysis,brief,
                source_status,model_metadata,prompt_metadata,favorite)
                VALUES (:id,'x','migration-channel','','Original','{}','{}','{}','{}','{}','{}',false)"""
                ),
                {"id": other_id},
            )
            conn.execute(
                text(
                    """INSERT INTO creator_works (id,creator_id,platform,origin,source_content_id)
                VALUES (:id,:creator,'youtube','source','video-1')"""
                ),
                {"id": uuid4(), "creator": creator_id},
            )
        with pytest.raises(IntegrityError):
            with database_engine.begin() as conn:
                conn.execute(
                    text(
                        """INSERT INTO creator_contacts
                    (id,creator_id,email,source_type,is_manual,validation_state,priority,is_active)
                    VALUES (:id,:creator,'ONE@example.com','manual',true,'unverified',0,true)"""
                    ),
                    {"id": uuid4(), "creator": creator_id},
                )
        with pytest.raises(RuntimeError, match="creator library data"):
            command.downgrade(alembic_config, "20260908_0008")
        with database_engine.connect() as conn:
            assert (
                conn.scalar(
                    text("SELECT count(*) FROM creator_contacts WHERE creator_id=:id"),
                    {"id": creator_id},
                )
                == 3
            )
            assert (
                conn.scalar(
                    text("SELECT count(*) FROM creator_works WHERE creator_id=:id"),
                    {"id": creator_id},
                )
                == 2
            )
    finally:
        with database_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM creator_profiles WHERE id IN (:a,:b)"),
                {"a": creator_id, "b": other_id},
            )
        command.upgrade(alembic_config, "head")
