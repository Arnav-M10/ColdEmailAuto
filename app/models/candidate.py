from enum import StrEnum

from sqlalchemy import Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin


class CandidateStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    SCREENING = "SCREENING"
    SCREENED = "SCREENED"
    SHORTLISTED = "SHORTLISTED"
    PAPERS_FOUND = "PAPERS_FOUND"
    PAPER_RETRIEVAL_PENDING = "PAPER_RETRIEVAL_PENDING"
    PAPER_ANALYZED = "PAPER_ANALYZED"
    DRAFT_READY = "DRAFT_READY"
    OUTLOOK_DRAFT_CREATED = "OUTLOOK_DRAFT_CREATED"
    SENT = "SENT"
    REPLIED = "REPLIED"
    DECLINED = "DECLINED"
    FOLLOW_UP_DUE = "FOLLOW_UP_DUE"
    CLOSED = "CLOSED"
    SKIPPED = "SKIPPED"
    NO_VERIFIED_EMAIL = "NO_VERIFIED_EMAIL"
    NO_FULL_TEXT = "NO_FULL_TEXT"
    DUPLICATE = "DUPLICATE"


class Candidate(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(240), nullable=False)
    title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    institution: Mapped[str | None] = mapped_column(String(240), nullable=True)
    department: Mapped[str | None] = mapped_column(String(240), nullable=True)
    research_area: Mapped[str | None] = mapped_column(String(500), nullable=True)
    official_profile_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    status: Mapped[CandidateStatus] = mapped_column(
        Enum(CandidateStatus, native_enum=False, length=40),
        nullable=False,
        default=CandidateStatus.DISCOVERED,
    )
