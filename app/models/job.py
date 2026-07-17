from enum import StrEnum

from sqlalchemy import Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        String(30),
        nullable=False,
        default=JobStatus.QUEUED,
    )
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    user_message: Mapped[str | None] = mapped_column(Text, nullable=True)

