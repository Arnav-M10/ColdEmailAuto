"""Create foundation tables.

Revision ID: 0001_create_foundation_tables
Revises: None
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_create_foundation_tables"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=True),
        sa.Column("entity_id", sa.String(length=80), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_table(
        "candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=240), nullable=False),
        sa.Column("institution", sa.String(length=240), nullable=True),
        sa.Column("status", sa.Enum(
            "DISCOVERED",
            "SCREENING",
            "SCREENED",
            "SHORTLISTED",
            "PAPERS_FOUND",
            "PAPER_RETRIEVAL_PENDING",
            "PAPER_ANALYZED",
            "DRAFT_READY",
            "OUTLOOK_DRAFT_CREATED",
            "SENT",
            "REPLIED",
            "DECLINED",
            "FOLLOW_UP_DUE",
            "CLOSED",
            "SKIPPED",
            "NO_VERIFIED_EMAIL",
            "NO_FULL_TEXT",
            "DUPLICATE",
            name="candidatestatus",
            native_enum=False,
            length=40,
        ), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("user_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("jobs")
    op.drop_table("candidates")
    op.drop_table("audit_events")
