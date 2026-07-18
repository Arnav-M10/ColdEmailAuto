"""Add research intelligence workflow tables.

Revision ID: 0009_research_workflow_runs
Revises: 0008_publication_selection
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_research_workflow_runs"
down_revision: str | None = "0008_publication_selection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "researcher_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("candidate_id", sa.Integer(), sa.ForeignKey("candidates.id"), nullable=False),
        sa.Column("cache_key", sa.String(length=64), nullable=False, unique=True),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("prompt_version", sa.String(length=80), nullable=False),
        sa.Column("publication_metadata_version", sa.String(length=64), nullable=False),
        sa.Column("papers_analyzed_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("themes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("clusters_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("methods_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("datasets_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("techniques_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("collaborators_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("active_projects_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("portfolio_connections_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("recent_direction", sa.Text(), nullable=True),
        sa.Column("balance", sa.String(length=160), nullable=True),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True,
    )
    op.create_table(
        "research_workflow_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("candidate_id", sa.Integer(), sa.ForeignKey("candidates.id"), nullable=False),
        sa.Column(
            "researcher_profile_id",
            sa.Integer(),
            sa.ForeignKey("researcher_profiles.id"),
            nullable=True,
        ),
        sa.Column(
            "selected_publication_id",
            sa.Integer(),
            sa.ForeignKey("publications.id"),
            nullable=True,
        ),
        sa.Column("paper_file_id", sa.Integer(), sa.ForeignKey("paper_files.id"), nullable=True),
        sa.Column("analysis_id", sa.Integer(), sa.ForeignKey("paper_analyses.id"), nullable=True),
        sa.Column("draft_id", sa.Integer(), sa.ForeignKey("drafts.id"), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("current_stage", sa.String(length=80), nullable=False),
        sa.Column("failed_stage", sa.String(length=80), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("selection_score", sa.Float(), nullable=True),
        sa.Column("selection_reasons_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("rejected_alternatives_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("retrieval_result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("claim_check_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("ai_request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("research_workflow_runs")
    op.drop_table("researcher_profiles")
