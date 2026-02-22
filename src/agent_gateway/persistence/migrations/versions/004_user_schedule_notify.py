"""Add notify column to user_schedules for notification delivery.

Revision ID: 004
Revises: 003
Create Date: 2026-02-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user_schedules", sa.Column("notify", sa.JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("user_schedules", "notify")
