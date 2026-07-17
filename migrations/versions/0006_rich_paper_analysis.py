"""Add rich paper analysis fields.

Revision ID: 0006_rich_paper_analysis
Revises: 0005_paper_retrieval_provenance
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_rich_paper_analysis"
down_revision: str | None = "0005_paper_retrieval_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("paper_files") as batch_op:
        batch_op.add_column(
            sa.Column("text_quality_json", sa.Text(), nullable=False, server_default="{}"),
        )
    with op.batch_alter_table("paper_analyses") as batch_op:
        batch_op.add_column(sa.Column("equations", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("computational_methods", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("datasets", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("software", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("assumptions", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("limitations", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("future_work", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("contribution_areas", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("candidate_role_notes", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("overclaim_risks", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("paper_analyses") as batch_op:
        batch_op.drop_column("overclaim_risks")
        batch_op.drop_column("candidate_role_notes")
        batch_op.drop_column("contribution_areas")
        batch_op.drop_column("future_work")
        batch_op.drop_column("limitations")
        batch_op.drop_column("assumptions")
        batch_op.drop_column("software")
        batch_op.drop_column("datasets")
        batch_op.drop_column("computational_methods")
        batch_op.drop_column("equations")
    with op.batch_alter_table("paper_files") as batch_op:
        batch_op.drop_column("text_quality_json")
