"""Add discovery review tables.

Revision ID: 0003_discovery_review_tables
Revises: 0002_manual_tracker_tables
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_discovery_review_tables"
down_revision: str | None = "0002_manual_tracker_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "department_imports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.String(length=1000), nullable=False),
        sa.Column("final_url", sa.String(length=1000), nullable=False),
        sa.Column("source_title", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("robots_allowed", sa.Boolean(), nullable=False),
        sa.Column("page_sha256", sa.String(length=64), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_table(
        "discovery_candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("import_id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=240), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=True),
        sa.Column("institution", sa.String(length=240), nullable=True),
        sa.Column("department", sa.String(length=240), nullable=True),
        sa.Column("role_category", sa.String(length=80), nullable=True),
        sa.Column("research_summary", sa.Text(), nullable=True),
        sa.Column("active_topics", sa.Text(), nullable=True),
        sa.Column("remote_feasibility", sa.Text(), nullable=True),
        sa.Column("mentoring_likelihood", sa.Text(), nullable=True),
        sa.Column("research_overlap", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("official_email", sa.String(length=320), nullable=True),
        sa.Column("official_homepage", sa.String(length=1000), nullable=True),
        sa.Column("source_url", sa.String(length=1000), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("warnings_json", sa.Text(), nullable=False),
        sa.Column("decision", sa.String(length=40), nullable=False),
        sa.Column("saved_candidate_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["import_id"], ["department_imports.id"]),
        sa.ForeignKeyConstraint(["saved_candidate_id"], ["candidates.id"]),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("discovery_candidates")
    op.drop_table("department_imports")
