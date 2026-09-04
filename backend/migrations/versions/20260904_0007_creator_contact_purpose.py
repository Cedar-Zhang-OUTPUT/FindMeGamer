"""Preserve the purpose of each Creator email contact.

Revision ID: 20260904_0007
Revises: 20260904_0006
Create Date: 2026-09-04
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260904_0007"
down_revision: str | None = "20260904_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "creator_contacts",
        sa.Column("purpose", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("creator_contacts", "purpose")
