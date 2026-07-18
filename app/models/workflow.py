from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ResearchWorkflowRun(Base, TimestampMixin):
    __tablename__ = "research_workflow_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), nullable=False)
    selected_publication_id: Mapped[int | None] = mapped_column(
        ForeignKey("publications.id"),
        nullable=True,
    )
    paper_file_id: Mapped[int | None] = mapped_column(ForeignKey("paper_files.id"), nullable=True)
    analysis_id: Mapped[int | None] = mapped_column(
        ForeignKey("paper_analyses.id"),
        nullable=True,
    )
    draft_id: Mapped[int | None] = mapped_column(ForeignKey("drafts.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="RUNNING")
    current_stage: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default="Finding publications",
    )
    failed_stage: Mapped[str | None] = mapped_column(String(80), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    selection_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    selection_reasons_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    rejected_alternatives_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    retrieval_result_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
