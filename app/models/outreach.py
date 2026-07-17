from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class OutreachEventType(StrEnum):
    CREATED = "CREATED"
    STATUS_CHANGED = "STATUS_CHANGED"
    EMAIL_ADDED = "EMAIL_ADDED"
    PAPER_UPLOADED = "PAPER_UPLOADED"
    ANALYSIS_ADDED = "ANALYSIS_ADDED"
    DRAFT_CREATED = "DRAFT_CREATED"
    DRAFT_APPROVED = "DRAFT_APPROVED"
    MANUALLY_MARKED_SENT = "MANUALLY_MARKED_SENT"
    FOLLOW_UP_SCHEDULED = "FOLLOW_UP_SCHEDULED"
    FOLLOW_UP_COMPLETED = "FOLLOW_UP_COMPLETED"
    REPLY_RECORDED = "REPLY_RECORDED"
    DECLINED = "DECLINED"


class OutreachEvent(Base, TimestampMixin):
    __tablename__ = "outreach_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), nullable=False)
    event_type: Mapped[OutreachEventType] = mapped_column(String(80), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class FollowUpTask(Base, TimestampMixin):
    __tablename__ = "follow_up_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="OPEN")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
