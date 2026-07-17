from app.models.candidate import CandidateStatus

ALLOWED_TRANSITIONS: dict[CandidateStatus, set[CandidateStatus]] = {
    CandidateStatus.DISCOVERED: {
        CandidateStatus.SCREENING,
        CandidateStatus.SKIPPED,
        CandidateStatus.DUPLICATE,
        CandidateStatus.NO_VERIFIED_EMAIL,
    },
    CandidateStatus.SCREENING: {
        CandidateStatus.SCREENED,
        CandidateStatus.NO_VERIFIED_EMAIL,
        CandidateStatus.DUPLICATE,
        CandidateStatus.SKIPPED,
    },
    CandidateStatus.SCREENED: {
        CandidateStatus.SHORTLISTED,
        CandidateStatus.SKIPPED,
        CandidateStatus.NO_VERIFIED_EMAIL,
    },
    CandidateStatus.SHORTLISTED: {
        CandidateStatus.PAPER_RETRIEVAL_PENDING,
        CandidateStatus.PAPERS_FOUND,
        CandidateStatus.NO_FULL_TEXT,
        CandidateStatus.SKIPPED,
    },
    CandidateStatus.PAPERS_FOUND: {
        CandidateStatus.PAPER_RETRIEVAL_PENDING,
        CandidateStatus.NO_FULL_TEXT,
    },
    CandidateStatus.PAPER_RETRIEVAL_PENDING: {
        CandidateStatus.PAPER_ANALYZED,
        CandidateStatus.NO_FULL_TEXT,
    },
    CandidateStatus.PAPER_ANALYZED: {
        CandidateStatus.DRAFT_READY,
        CandidateStatus.CLOSED,
    },
    CandidateStatus.DRAFT_READY: {
        CandidateStatus.OUTLOOK_DRAFT_CREATED,
        CandidateStatus.CLOSED,
    },
    CandidateStatus.OUTLOOK_DRAFT_CREATED: {
        CandidateStatus.SENT,
        CandidateStatus.CLOSED,
    },
    CandidateStatus.SENT: {
        CandidateStatus.REPLIED,
        CandidateStatus.FOLLOW_UP_DUE,
        CandidateStatus.DECLINED,
        CandidateStatus.CLOSED,
    },
    CandidateStatus.FOLLOW_UP_DUE: {
        CandidateStatus.REPLIED,
        CandidateStatus.DECLINED,
        CandidateStatus.CLOSED,
    },
    CandidateStatus.REPLIED: {
        CandidateStatus.DECLINED,
        CandidateStatus.CLOSED,
    },
}

TERMINAL_STATUSES = {
    CandidateStatus.DECLINED,
    CandidateStatus.CLOSED,
    CandidateStatus.SKIPPED,
    CandidateStatus.NO_VERIFIED_EMAIL,
    CandidateStatus.NO_FULL_TEXT,
    CandidateStatus.DUPLICATE,
}


def can_transition(current: CandidateStatus, target: CandidateStatus) -> bool:
    if current == target:
        return True
    if current in TERMINAL_STATUSES:
        return False
    return target in ALLOWED_TRANSITIONS.get(current, set())


def validate_transition(current: CandidateStatus, target: CandidateStatus) -> None:
    if not can_transition(current, target):
        raise ValueError(f"Invalid candidate status transition: {current} -> {target}")
