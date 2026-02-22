"""Add user_schedules table for per-user cron schedules.

Revision ID: 003
Revises: 002
Create Date: 2026-02-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_schedules",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("user_id", sa.String, nullable=False),
        sa.Column("agent_id", sa.String, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("cron_expr", sa.String, nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("input", sa.JSON),
        sa.Column("enabled", sa.Boolean, default=True),
        sa.Column("timezone", sa.String, default="UTC"),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_user_schedules_user_id", "user_schedules", ["user_id"])
    op.create_index("ix_user_schedules_user_agent", "user_schedules", ["user_id", "agent_id"])


def downgrade() -> None:
    op.drop_index("ix_user_schedules_user_agent", table_name="user_schedules")
    op.drop_index("ix_user_schedules_user_id", table_name="user_schedules")
    op.drop_table("user_schedules")
