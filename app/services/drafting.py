from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.candidate import Candidate, CandidateStatus
from app.models.draft import Draft
from app.models.email_address import EmailAddress
from app.models.outreach import OutreachEventType
from app.models.paper import EvidenceItem, PaperAnalysis
from app.services.assets import required_attachments_ready
from app.services.candidates import record_event

FORBIDDEN_PHRASES = {
    "robust",
    "leverage",
    "groundbreaking",
    "compelling",
    "fascinating",
    "utilize",
    "endeavor",
    "delve",
    "pivotal",
    "transformative",
    "very interesting",
}


def word_count(text: str) -> int:
    body = text.split("Sincerely,", maxsplit=1)[0]
    return len([word for word in body.replace("\n", " ").split(" ") if word.strip()])


def contains_forbidden_phrase(text: str) -> list[str]:
    lowered = text.lower()
    return sorted(phrase for phrase in FORBIDDEN_PHRASES if phrase in lowered)


def primary_verified_email(session: Session, candidate_id: int) -> EmailAddress | None:
    return session.scalars(
        select(EmailAddress)
        .where(
            EmailAddress.candidate_id == candidate_id,
            EmailAddress.verification_status == "VERIFIED",
        )
        .order_by(EmailAddress.created_at.desc()),
    ).first()


def generate_manual_draft(
    session: Session,
    *,
    candidate: Candidate,
    analysis: PaperAnalysis,
    evidence: EvidenceItem,
) -> Draft:
    last_name = candidate.full_name.strip().split()[-1]
    body = (
        f"Dear Professor {last_name},\n\n"
        "I am an incoming student at the Texas Academy of Mathematics and Science at the "
        "University of North Texas. "
        f"I enjoyed reading your paper on {analysis.title}. "
        f"I was mainly intrigued by {evidence.claim}. "
        f"The part I noted from the paper was: {evidence.evidence_text[:180].strip()}.\n\n"
        f"My recent work includes {analysis.connection_to_arnav}. "
        "I would be glad to help with any suitable ongoing project through coding, "
        "data analysis, numerical checks, or visualization. "
        "I have attached my resume and research portfolio for context.\n\n"
        "Sincerely,\n"
        "Arnav Mittal\n"
        "Incoming Student, TAMS\n"
        "University of North Texas\n"
        "ArnavMittal@my.unt.edu"
    )
    draft = Draft(
        candidate_id=candidate.id,
        subject=f"Research inquiry - {analysis.title[:60]}",
        body_text=body,
        body_html=None,
        word_count=word_count(body),
        generation_version="manual-analysis-v1",
        approved_by_user=False,
    )
    session.add(draft)
    candidate.status = CandidateStatus.DRAFT_READY
    record_event(
        session,
        candidate_id=candidate.id,
        event_type=OutreachEventType.DRAFT_CREATED,
        notes=f"Draft generated from analysis {analysis.id}.",
    )
    return draft


def validate_draft_approval(
    session: Session,
    *,
    draft: Draft,
    project_root_override: Path | None = None,
) -> list[str]:
    errors: list[str] = []
    if primary_verified_email(session, draft.candidate_id) is None:
        errors.append("A verified official email is required.")
    if contains_forbidden_phrase(draft.body_text):
        errors.append("Draft contains forbidden wording.")
    if draft.word_count < 80:
        errors.append("Draft is too short for review.")
    if not required_attachments_ready(project_root_override):
        errors.append("Required resume and portfolio PDFs must be valid.")
    return errors


def approve_draft(session: Session, draft: Draft) -> None:
    errors = validate_draft_approval(session, draft=draft)
    if errors:
        raise ValueError("; ".join(errors))
    draft.approved_by_user = True
    draft.approved_at = datetime.now(UTC)
    record_event(
        session,
        candidate_id=draft.candidate_id,
        event_type=OutreachEventType.DRAFT_APPROVED,
        notes="Draft approved locally. Outlook integration is not implemented.",
    )


def list_drafts(session: Session) -> list[Draft]:
    return list(session.scalars(select(Draft).order_by(Draft.created_at.desc())))


def get_draft(session: Session, draft_id: int) -> Draft | None:
    return session.get(Draft, draft_id)
