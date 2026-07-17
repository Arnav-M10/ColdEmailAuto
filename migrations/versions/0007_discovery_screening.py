"""Add discovery screening fields.

Revision ID: 0007_discovery_screening
Revises: 0006_rich_paper_analysis
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_discovery_screening"
down_revision: str | None = "0006_rich_paper_analysis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("discovery_candidates") as batch_op:
        batch_op.add_column(
            sa.Column(
                "screening_status",
                sa.String(length=40),
                nullable=False,
                server_default="INCLUDED",
            ),
        )
        batch_op.add_column(
            sa.Column("screening_score", sa.Float(), nullable=False, server_default="0"),
        )
        batch_op.add_column(
            sa.Column("screening_reasons_json", sa.Text(), nullable=False, server_default="[]"),
        )
        batch_op.add_column(
            sa.Column("exclusion_reasons_json", sa.Text(), nullable=False, server_default="[]"),
        )
        batch_op.add_column(
            sa.Column("warning_reasons_json", sa.Text(), nullable=False, server_default="[]"),
        )
        batch_op.add_column(
            sa.Column("override_exclusion", sa.Boolean(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    with op.batch_alter_table("discovery_candidates") as batch_op:
        batch_op.drop_column("override_exclusion")
        batch_op.drop_column("warning_reasons_json")
        batch_op.drop_column("exclusion_reasons_json")
        batch_op.drop_column("screening_reasons_json")
        batch_op.drop_column("screening_score")
        batch_op.drop_column("screening_status")
