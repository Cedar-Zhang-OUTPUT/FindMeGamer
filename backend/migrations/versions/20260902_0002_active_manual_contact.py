"""Enforce one active manual contact per Creator.

Revision ID: 20260902_0002
Revises: 20260902_0001
Create Date: 2026-09-02
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260902_0002"
down_revision: str | None = "20260902_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        WITH ranked_manual_contacts AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY creator_id
                    ORDER BY updated_at DESC, created_at DESC, id DESC
                ) AS active_order
            FROM creator_contacts
            WHERE is_manual AND is_active
        )
        UPDATE creator_contacts AS contact
        SET is_active = false, updated_at = now()
        FROM ranked_manual_contacts AS ranked
        WHERE contact.id = ranked.id AND ranked.active_order > 1
        """
    )
    op.create_index(
        "uq_creator_contacts_active_manual",
        "creator_contacts",
        ["creator_id"],
        unique=True,
        postgresql_where=sa.text("is_manual AND is_active"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_creator_contacts_active_manual", table_name="creator_contacts"
    )
