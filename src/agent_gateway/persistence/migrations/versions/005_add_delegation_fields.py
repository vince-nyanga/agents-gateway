"""Add delegation fields to executions table.

Revision ID: 005
Revises: 004
Create Date: 2026-02-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("executions", sa.Column("parent_execution_id", sa.String(36), nullable=True))
    op.add_column("executions", sa.Column("root_execution_id", sa.String(36), nullable=True))
    op.add_column(
        "executions",
        sa.Column("delegation_depth", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_executions_parent_execution_id", "executions", ["parent_execution_id"])
    op.create_index("ix_executions_root_execution_id", "executions", ["root_execution_id"])


def downgrade() -> None:
    op.drop_index("ix_executions_root_execution_id", table_name="executions")
    op.drop_index("ix_executions_parent_execution_id", table_name="executions")
    op.drop_column("executions", "delegation_depth")
    op.drop_column("executions", "root_execution_id")
    op.drop_column("executions", "parent_execution_id")
