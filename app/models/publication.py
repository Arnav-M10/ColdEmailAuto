from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Publication(Base, TimestampMixin):
    __tablename__ = "publications"
    __table_args__ = (UniqueConstraint("title_fingerprint", name="uq_publications_title_fp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    title_fingerprint: Mapped[str] = mapped_column(String(500), nullable=False)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    venue: Mapped[str | None] = mapped_column(String(500), nullable=True)
    doi: Mapped[str | None] = mapped_column(String(300), nullable=True, unique=True)
    arxiv_id: Mapped[str | None] = mapped_column(String(80), nullable=True, unique=True)
    openalex_id: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    open_access_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    pdf_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    author_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    citation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    work_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class Authorship(Base, TimestampMixin):
    __tablename__ = "authorships"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id",
            "publication_id",
            name="uq_authorship_candidate_publication",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), nullable=False)
    publication_id: Mapped[int] = mapped_column(ForeignKey("publications.id"), nullable=False)
    author_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    author_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    openalex_author_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    confirmed_author_present: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    corresponding_author: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    role: Mapped[str | None] = mapped_column(String(80), nullable=True)
    identity_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    match_status: Mapped[str] = mapped_column(String(40), nullable=False, default="REVIEW_REQUIRED")
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    connection_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    score_details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    selected_for_retrieval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    selection_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
