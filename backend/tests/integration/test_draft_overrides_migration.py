"""Apply the actual 0023 operation to a populated 0022-shaped table."""

import importlib.util
from pathlib import Path
from uuid import UUID

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from tests.integration.test_outreach_drafts import draft_setup, compose, manual


def test_0022_drafts_upgrade_preserves_existing_values_and_source_history(
    auth_client, session, monkeypatch
):
    activity, _, batch, template = draft_setup(
        auth_client, session, monkeypatch, count=2
    )
    composition = compose(auth_client, activity, batch, template).json()
    draft = manual(auth_client, composition["drafts"][0]).json()
    connection = session.connection()
    connection.execute(text("ALTER TABLE outreach_drafts DROP COLUMN manual_overrides"))
    pending_id = {"id": UUID(composition["drafts"][1]["id"])}
    connection.execute(
        text("UPDATE outreach_drafts SET values='null'::jsonb WHERE id=:id"), pending_id
    )
    identity = {"id": UUID(draft["id"])}
    before = connection.scalar(
        text("SELECT to_jsonb(d) FROM outreach_drafts d WHERE id=:id"), identity
    )
    source_before = (
        connection.execute(
            text("SELECT to_jsonb(r) FROM activity_recipient_snapshots r ORDER BY id")
        )
        .scalars()
        .all()
    )
    path = (
        Path(__file__).parents[2]
        / "migrations/versions/20260913_0023_draft_overrides.py"
    )
    spec = importlib.util.spec_from_file_location("draft_override_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "20260910_0022"
    with Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()
    after = connection.scalar(
        text("SELECT to_jsonb(d) FROM outreach_drafts d WHERE id=:id"), identity
    )
    assert after.pop("manual_overrides") == before["values"]
    assert after == before
    assert (
        connection.scalar(
            text("SELECT manual_overrides FROM outreach_drafts WHERE id=:id"),
            pending_id,
        )
        == {}
    )
    assert (
        connection.execute(
            text("SELECT to_jsonb(r) FROM activity_recipient_snapshots r ORDER BY id")
        )
        .scalars()
        .all()
        == source_before
    )
