"""Add publication metadata tables.

Revision ID: 0004_publication_metadata_tables
Revises: 0003_discovery_review_tables
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_publication_metadata_tables"
down_revision: str | None = "0003_discovery_review_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "publications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=1000), nullable=False),
        sa.Column("title_fingerprint", sa.String(length=500), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("venue", sa.String(length=500), nullable=True),
        sa.Column("doi", sa.String(length=300), nullable=True),
        sa.Column("arxiv_id", sa.String(length=80), nullable=True),
        sa.Column("openalex_id", sa.String(length=200), nullable=True),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("open_access_url", sa.String(length=1000), nullable=True),
        sa.Column("pdf_url", sa.String(length=1000), nullable=True),
        sa.Column("author_count", sa.Integer(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("arxiv_id"),
        sa.UniqueConstraint("doi"),
        sa.UniqueConstraint("openalex_id"),
        sa.UniqueConstraint("title_fingerprint", name="uq_publications_title_fp"),
        if_not_exists=True,
    )
    op.create_table(
        "authorships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("publication_id", sa.Integer(), nullable=False),
        sa.Column("author_position", sa.Integer(), nullable=True),
        sa.Column("author_count", sa.Integer(), nullable=True),
        sa.Column("role", sa.String(length=80), nullable=True),
        sa.Column("identity_confidence", sa.Float(), nullable=False),
        sa.Column("match_status", sa.String(length=40), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("connection_summary", sa.Text(), nullable=True),
        sa.Column("warnings_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"]),
        sa.ForeignKeyConstraint(["publication_id"], ["publications.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "candidate_id",
            "publication_id",
            name="uq_authorship_candidate_publication",
        ),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("authorships")
    op.drop_table("publications")
