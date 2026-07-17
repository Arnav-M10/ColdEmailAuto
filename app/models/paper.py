from enum import StrEnum

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class EvidenceClassification(StrEnum):
    EXPLICIT = "EXPLICIT"
    STRONG_INFERENCE = "STRONG_INFERENCE"
    SPECULATIVE = "SPECULATIVE"


class PaperFile(Base, TimestampMixin):
    __tablename__ = "paper_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), nullable=False)
    publication_id: Mapped[int | None] = mapped_column(ForeignKey("publications.id"), nullable=True)
    original_filename: Mapped[str] = mapped_column(String(300), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    parsed_text_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    license_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    text_quality_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class PaperAnalysis(Base, TimestampMixin):
    __tablename__ = "paper_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), nullable=False)
    paper_file_id: Mapped[int] = mapped_column(ForeignKey("paper_files.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    research_question: Mapped[str] = mapped_column(Text, nullable=False)
    methods: Mapped[str] = mapped_column(Text, nullable=False)
    results: Mapped[str] = mapped_column(Text, nullable=False)
    equations: Mapped[str | None] = mapped_column(Text, nullable=True)
    computational_methods: Mapped[str | None] = mapped_column(Text, nullable=True)
    datasets: Mapped[str | None] = mapped_column(Text, nullable=True)
    software: Mapped[str | None] = mapped_column(Text, nullable=True)
    assumptions: Mapped[str | None] = mapped_column(Text, nullable=True)
    limitations: Mapped[str | None] = mapped_column(Text, nullable=True)
    future_work: Mapped[str | None] = mapped_column(Text, nullable=True)
    contribution_areas: Mapped[str | None] = mapped_column(Text, nullable=True)
    candidate_role_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    overclaim_risks: Mapped[str | None] = mapped_column(Text, nullable=True)
    connection_to_arnav: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    provider: Mapped[str] = mapped_column(String(80), nullable=False, default="manual")


class EvidenceItem(Base, TimestampMixin):
    __tablename__ = "evidence_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("paper_analyses.id"), nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_text: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    section_name: Mapped[str] = mapped_column(String(160), nullable=False, default="Unknown")
    classification: Mapped[EvidenceClassification] = mapped_column(String(40), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
