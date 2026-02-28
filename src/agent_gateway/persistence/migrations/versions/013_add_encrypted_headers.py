"""Add encrypted_headers column to mcp_servers table.

Revision ID: 013
Revises: 012
Create Date: 2026-02-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "013"
down_revision: str | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mcp_servers", sa.Column("encrypted_headers", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("mcp_servers", "encrypted_headers")
