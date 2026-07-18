from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ResearcherProfile(Base, TimestampMixin):
    __tablename__ = "researcher_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), nullable=False)
    cache_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    publication_metadata_version: Mapped[str] = mapped_column(String(64), nullable=False)
    papers_analyzed_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    themes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    clusters_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    methods_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    datasets_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    techniques_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    collaborators_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    active_projects_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    portfolio_connections_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    recent_direction: Mapped[str | None] = mapped_column(Text, nullable=True)
    balance: Mapped[str | None] = mapped_column(String(160), nullable=True)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
