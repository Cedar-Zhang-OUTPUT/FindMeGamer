from uuid import uuid4
import pytest
from alembic import command
from sqlalchemy import text, inspect
from sqlalchemy.orm import Session
from app.db.models.profiles import GameProfile, CreatorProfile
from app.db.models.discovery import Activity, DiscoveryQuery, DiscoveryCandidate
from app.db.models.activity_outreach import ActivitySelection, RecipientBatch
from app.db.models.outreach_drafts import OutreachTemplateVersion, OutreachComposition
from app.db.models.activity_sending import ActivitySendBatch
from app.db.models.activity_collaboration import ActivityCollaboration, ActivityResponse
from app.core.idempotency import utc_now


def test_0017_upgrade_keeps_final_batch_and_guards_manual_response_history(
    migrated_database, alembic_config, database_engine
):
    owned = []
    selection_id = None
    try:
        command.downgrade(alembic_config, "20260908_0017")
        with Session(database_engine) as session:

            def add(row):
                session.add(row)
                session.flush()
                owned.append((row.__tablename__, row.id))
                return row

            game = add(
                GameProfile(
                    canonical_url="https://example.test/c-migration", sort_name="Game"
                )
            )
            creator = add(
                CreatorProfile(
                    canonical_url="https://example.test/creator", sort_name="Creator"
                )
            )
            activity = add(Activity(game_id=game.id, name="Existing Activity"))
            query = add(DiscoveryQuery(activity_id=activity.id))
            candidate = add(
                DiscoveryCandidate(
                    query_id=query.id,
                    creator_id=creator.id,
                    platform="x",
                    account_id="123",
                    ordinal=0,
                )
            )
            selection = add(
                ActivitySelection(
                    activity_id=activity.id,
                    creator_id=creator.id,
                    candidate_id=candidate.id,
                    platform="x",
                    account_id="123",
                )
            )
            recipient_batch = add(
                RecipientBatch(
                    activity_id=activity.id, request_id=uuid4(), request_hash="fixture"
                )
            )
            template = add(
                OutreachTemplateVersion(
                    game_id=game.id,
                    name="Original",
                    subject="Subject",
                    fixed_fragments=["a", "b", "c", "d", "e"],
                    fixed_hash="fixture",
                    source_metadata={},
                )
            )
            composition = add(
                OutreachComposition(
                    activity_id=activity.id,
                    recipient_batch_id=recipient_batch.id,
                    template_version_id=template.id,
                    request_id=uuid4(),
                    request_hash="fixture",
                )
            )
            batch = add(
                ActivitySendBatch(
                    activity_id=activity.id,
                    composition_id=composition.id,
                    request_id=uuid4(),
                    request_hash="fixture",
                    qualification_snapshot={"retained": "exact"},
                )
            )
            batch_id, selection_id = batch.id, selection.id
            session.commit()
        with database_engine.connect() as connection:
            before = connection.scalar(
                text("SELECT to_jsonb(b) FROM activity_send_batches b WHERE id=:id"),
                {"id": batch_id},
            )
            settings = (
                connection.execute(
                    text("SELECT to_jsonb(s) FROM shared_settings s ORDER BY id")
                )
                .scalars()
                .all()
            )
        command.upgrade(alembic_config, "head")
        with database_engine.connect() as connection:
            assert (
                connection.scalar(
                    text(
                        "SELECT to_jsonb(b) FROM activity_send_batches b WHERE id=:id"
                    ),
                    {"id": batch_id},
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
        with Session(database_engine) as session:
            session.add(
                ActivityCollaboration(
                    selection_id=selection_id, revision=1, notes="Preserve"
                )
            )
            session.flush()
            session.add(
                ActivityResponse(
                    selection_id=selection_id,
                    revision=1,
                    outcome="accepted",
                    source_note="Recorded email",
                    responded_at=utc_now(),
                )
            )
            session.commit()
        with pytest.raises(RuntimeError, match="Back up"):
            command.downgrade(alembic_config, "20260908_0017")
        with database_engine.connect() as connection:
            assert (
                connection.scalar(
                    text(
                        "SELECT outcome FROM activity_responses WHERE selection_id=:id"
                    ),
                    {"id": selection_id},
                )
                == "accepted"
            )
    finally:
        with database_engine.begin() as connection:
            tables = inspect(connection).get_table_names()
            if "activity_responses" in tables and selection_id is not None:
                connection.execute(
                    text("DELETE FROM activity_responses WHERE selection_id=:id"),
                    {"id": selection_id},
                )
                connection.execute(
                    text("DELETE FROM activity_collaborations WHERE selection_id=:id"),
                    {"id": selection_id},
                )
            for table, identity in reversed(owned):
                connection.execute(
                    text(f"DELETE FROM {table} WHERE id=:id"), {"id": identity}
                )
        command.upgrade(alembic_config, "head")
