"""Add paper retrieval provenance.

Revision ID: 0005_paper_retrieval_provenance
Revises: 0004_publication_metadata_tables
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_paper_retrieval_provenance"
down_revision: str | None = "0004_publication_metadata_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("paper_files") as batch_op:
        batch_op.add_column(sa.Column("publication_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("source_url", sa.String(length=1000), nullable=True))
        batch_op.add_column(sa.Column("license_note", sa.String(length=500), nullable=True))
        batch_op.create_foreign_key(
            "fk_paper_files_publication_id",
            "publications",
            ["publication_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("paper_files") as batch_op:
        batch_op.drop_constraint("fk_paper_files_publication_id", type_="foreignkey")
        batch_op.drop_column("license_note")
        batch_op.drop_column("source_url")
        batch_op.drop_column("publication_id")
