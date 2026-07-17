"""Add publication selection gate.

Revision ID: 0008_publication_selection
Revises: 0007_discovery_screening
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_publication_selection"
down_revision: str | None = "0007_discovery_screening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("authorships") as batch_op:
        batch_op.add_column(
            sa.Column("selected_for_retrieval", sa.Boolean(), nullable=False, server_default="0"),
        )
        batch_op.add_column(sa.Column("selected_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("selection_notes", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("authorships") as batch_op:
        batch_op.drop_column("selection_notes")
        batch_op.drop_column("selected_at")
        batch_op.drop_column("selected_for_retrieval")
