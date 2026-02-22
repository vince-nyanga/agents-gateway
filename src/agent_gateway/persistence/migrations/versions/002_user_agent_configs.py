"""Add user_agent_configs table for per-user agent configuration.

Revision ID: 002
Revises: 001
Create Date: 2026-02-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_agent_configs",
        sa.Column("user_id", sa.String, nullable=False, primary_key=True),
        sa.Column("agent_id", sa.String, nullable=False, primary_key=True),
        sa.Column("instructions", sa.Text, nullable=True),
        sa.Column("config_values", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("encrypted_secrets", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("setup_completed", sa.Boolean, nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_user_agent_configs_user_id", "user_agent_configs", ["user_id"])
    op.create_index("ix_user_agent_configs_agent_id", "user_agent_configs", ["agent_id"])


def downgrade() -> None:
    op.drop_index("ix_user_agent_configs_agent_id", table_name="user_agent_configs")
    op.drop_index("ix_user_agent_configs_user_id", table_name="user_agent_configs")
    op.drop_table("user_agent_configs")
