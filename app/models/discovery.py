from enum import StrEnum

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class DepartmentImportStatus(StrEnum):
    FETCHED = "FETCHED"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"
    REVIEW_READY = "REVIEW_READY"
    COMPLETED = "COMPLETED"


class DiscoveryDecision(StrEnum):
    REVIEW_PENDING = "REVIEW_PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SAVED = "SAVED"


class DiscoveryScreeningStatus(StrEnum):
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"
    WARN = "WARN"


class DepartmentImport(Base, TimestampMixin):
    __tablename__ = "department_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    final_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[DepartmentImportStatus] = mapped_column(String(40), nullable=False)
    robots_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    page_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class DiscoveryCandidate(Base, TimestampMixin):
    __tablename__ = "discovery_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_id: Mapped[int] = mapped_column(ForeignKey("department_imports.id"), nullable=False)
    full_name: Mapped[str] = mapped_column(String(240), nullable=False)
    title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    institution: Mapped[str | None] = mapped_column(String(240), nullable=True)
    department: Mapped[str | None] = mapped_column(String(240), nullable=True)
    role_category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    research_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    active_topics: Mapped[str | None] = mapped_column(Text, nullable=True)
    remote_feasibility: Mapped[str | None] = mapped_column(Text, nullable=True)
    mentoring_likelihood: Mapped[str | None] = mapped_column(Text, nullable=True)
    research_overlap: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    official_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    official_homepage: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    warnings_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    screening_status: Mapped[DiscoveryScreeningStatus] = mapped_column(
        String(40),
        nullable=False,
        default=DiscoveryScreeningStatus.INCLUDED,
    )
    screening_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    screening_reasons_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    exclusion_reasons_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    warning_reasons_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    override_exclusion: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    decision: Mapped[DiscoveryDecision] = mapped_column(
        String(40),
        nullable=False,
        default=DiscoveryDecision.REVIEW_PENDING,
    )
    saved_candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("candidates.id"),
        nullable=True,
    )
