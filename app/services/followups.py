from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.candidate import Candidate, CandidateStatus
from app.models.draft import Draft
from app.models.outreach import FollowUpTask, OutreachEventType
from app.services.candidates import record_event

DEFAULT_FOLLOW_UP_BUSINESS_DAYS = 8
MAX_FOLLOW_UPS_PER_CANDIDATE = 1


def add_business_days(start: date, business_days: int) -> date:
    if business_days < 0:
        raise ValueError("Business-day offset must be non-negative.")
    current = start
    added = 0
    while added < business_days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


def suggested_follow_up_due_date(
    sent_on: date,
    business_days: int = DEFAULT_FOLLOW_UP_BUSINESS_DAYS,
) -> date:
    return add_business_days(sent_on, business_days)


def approved_drafts_for_candidate(session: Session, candidate_id: int) -> list[Draft]:
    return list(
        session.scalars(
            select(Draft)
            .where(Draft.candidate_id == candidate_id, Draft.approved_by_user.is_(True))
            .order_by(Draft.approved_at.desc()),
        ),
    )


def list_follow_ups_for_candidate(session: Session, candidate_id: int) -> list[FollowUpTask]:
    return list(
        session.scalars(
            select(FollowUpTask)
            .where(FollowUpTask.candidate_id == candidate_id)
            .order_by(FollowUpTask.due_at.asc()),
        ),
    )


def list_follow_up_tasks(session: Session) -> list[FollowUpTask]:
    return list(session.scalars(select(FollowUpTask).order_by(FollowUpTask.due_at.asc())))


def get_follow_up_task(session: Session, task_id: int) -> FollowUpTask | None:
    return session.get(FollowUpTask, task_id)


def create_follow_up_task(
    session: Session,
    *,
    candidate: Candidate,
    sent_on: date,
    business_days: int = DEFAULT_FOLLOW_UP_BUSINESS_DAYS,
) -> FollowUpTask:
    if candidate.status == CandidateStatus.DECLINED:
        raise ValueError("Follow-ups are not allowed after an explicit decline.")
    existing_count = len(list_follow_ups_for_candidate(session, candidate.id))
    if existing_count >= MAX_FOLLOW_UPS_PER_CANDIDATE:
        raise ValueError("Only one follow-up is allowed for a candidate.")

    due_date = suggested_follow_up_due_date(sent_on, business_days)
    due_at = datetime.combine(due_date, time(hour=9), tzinfo=UTC)
    task = FollowUpTask(
        candidate_id=candidate.id,
        due_at=due_at,
        status="OPEN",
        notes=f"Suggested follow-up {business_days} business days after manual sent date.",
    )
    session.add(task)
    session.flush()
    if due_date <= date.today():
        candidate.status = CandidateStatus.FOLLOW_UP_DUE
    record_event(
        session,
        candidate_id=candidate.id,
        event_type=OutreachEventType.FOLLOW_UP_SCHEDULED,
        notes=f"Follow-up suggested for {due_date.isoformat()}.",
    )
    return task


def mark_candidate_manually_sent_and_schedule_follow_up(
    session: Session,
    *,
    candidate: Candidate,
    sent_on: date,
) -> FollowUpTask:
    if sent_on > date.today():
        raise ValueError("Manual sent date cannot be in the future.")
    if candidate.status == CandidateStatus.DECLINED:
        raise ValueError("A declined candidate cannot be marked sent.")
    if candidate.status not in {
        CandidateStatus.DRAFT_READY,
        CandidateStatus.OUTLOOK_DRAFT_CREATED,
        CandidateStatus.SENT,
    }:
        raise ValueError("A reviewed draft is required before marking a candidate sent.")
    if not approved_drafts_for_candidate(session, candidate.id):
        raise ValueError("At least one locally approved draft is required before marking sent.")

    if candidate.status != CandidateStatus.SENT:
        previous = candidate.status
        candidate.status = CandidateStatus.SENT
        record_event(
            session,
            candidate_id=candidate.id,
            event_type=OutreachEventType.MANUALLY_MARKED_SENT,
            notes=f"{previous} -> SENT on {sent_on.isoformat()} by manual tracking.",
        )
    return create_follow_up_task(session, candidate=candidate, sent_on=sent_on)


def complete_follow_up_task(session: Session, task: FollowUpTask) -> None:
    if task.status == "COMPLETED":
        return
    task.status = "COMPLETED"
    record_event(
        session,
        candidate_id=task.candidate_id,
        event_type=OutreachEventType.FOLLOW_UP_COMPLETED,
        notes="Follow-up task marked complete manually.",
    )
