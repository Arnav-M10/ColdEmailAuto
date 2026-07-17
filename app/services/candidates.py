import csv
import io
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import utc_now
from app.models.candidate import Candidate, CandidateStatus
from app.models.email_address import EmailAddress
from app.models.outreach import OutreachEvent, OutreachEventType
from app.services.status import validate_transition

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class DuplicateWarning:
    reason: str
    candidate_id: int
    candidate_name: str


@dataclass(frozen=True)
class CsvImportPreviewRow:
    row_number: int
    name: str
    email: str
    institution: str
    status: str
    valid: bool
    error: str | None


@dataclass(frozen=True)
class CsvImportResult:
    imported: int
    skipped: int
    errors: list[str]


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_email(email: str) -> str:
    normalized = normalize_email(email)
    if not EMAIL_RE.match(normalized):
        raise ValueError("Enter a valid official email address.")
    return normalized


def list_candidates(session: Session) -> list[Candidate]:
    return list(
        session.scalars(
            select(Candidate)
            .where(Candidate.deleted_at.is_(None))
            .order_by(Candidate.created_at.desc()),
        ),
    )


def get_candidate(session: Session, candidate_id: int) -> Candidate | None:
    return session.get(Candidate, candidate_id)


def detect_duplicate_warnings(
    session: Session,
    *,
    full_name: str,
    institution: str | None,
    email: str | None = None,
) -> list[DuplicateWarning]:
    warnings: list[DuplicateWarning] = []
    if email:
        normalized = normalize_email(email)
        existing_email = session.scalars(
            select(EmailAddress).where(func.lower(EmailAddress.email) == normalized),
        ).first()
        if existing_email:
            existing_candidate = session.get(Candidate, existing_email.candidate_id)
            if existing_candidate:
                warnings.append(
                    DuplicateWarning(
                        reason="Matching verified email",
                        candidate_id=existing_candidate.id,
                        candidate_name=existing_candidate.full_name,
                    ),
                )

    normalized_name = full_name.strip().lower()
    normalized_institution = (institution or "").strip().lower()
    if normalized_name and normalized_institution:
        existing_candidate = session.scalars(
            select(Candidate).where(
                func.lower(Candidate.full_name) == normalized_name,
                func.lower(Candidate.institution) == normalized_institution,
                Candidate.deleted_at.is_(None),
            ),
        ).first()
        if existing_candidate:
            warnings.append(
                DuplicateWarning(
                    reason="Matching name and institution",
                    candidate_id=existing_candidate.id,
                    candidate_name=existing_candidate.full_name,
                ),
            )
    return warnings


def create_candidate(
    session: Session,
    *,
    full_name: str,
    title: str | None,
    institution: str | None,
    department: str | None,
    research_area: str | None,
    official_profile_url: str | None,
    notes: str | None,
) -> Candidate:
    candidate = Candidate(
        full_name=full_name.strip(),
        title=title or None,
        institution=institution or None,
        department=department or None,
        research_area=research_area or None,
        official_profile_url=official_profile_url or None,
        notes=notes or None,
        status=CandidateStatus.DISCOVERED,
    )
    session.add(candidate)
    session.flush()
    record_event(
        session,
        candidate_id=candidate.id,
        event_type=OutreachEventType.CREATED,
        notes="Candidate entered manually.",
    )
    return candidate


def add_email_address(
    session: Session,
    *,
    candidate_id: int,
    email: str,
    source_url: str,
    source_type: str,
    confidence: str,
    verification_status: str,
) -> EmailAddress:
    normalized = validate_email(email)
    email_address = EmailAddress(
        candidate_id=candidate_id,
        email=normalized,
        source_url=source_url.strip(),
        source_type=source_type.strip(),
        confidence=confidence.strip().upper(),
        verification_status=verification_status.strip().upper(),
        retrieved_at=datetime.now(UTC),
        is_primary=True,
    )
    session.add(email_address)
    record_event(
        session,
        candidate_id=candidate_id,
        event_type=OutreachEventType.EMAIL_ADDED,
        notes=f"Official email recorded from {source_type}.",
    )
    return email_address


def change_status(session: Session, candidate: Candidate, target: CandidateStatus) -> None:
    validate_transition(candidate.status, target)
    previous = candidate.status
    candidate.status = target
    record_event(
        session,
        candidate_id=candidate.id,
        event_type=OutreachEventType.STATUS_CHANGED,
        notes=f"{previous} -> {target}",
    )


def record_event(
    session: Session,
    *,
    candidate_id: int,
    event_type: OutreachEventType,
    notes: str | None = None,
) -> OutreachEvent:
    event = OutreachEvent(candidate_id=candidate_id, event_type=event_type, notes=notes)
    session.add(event)
    return event


def soft_delete_candidate(session: Session, candidate: Candidate) -> None:
    candidate.deleted_at = utc_now()
    record_event(
        session,
        candidate_id=candidate.id,
        event_type=OutreachEventType.STATUS_CHANGED,
        notes="Candidate soft deleted.",
    )


def preview_contacted_csv(csv_text: str) -> list[CsvImportPreviewRow]:
    reader = csv.DictReader(io.StringIO(csv_text))
    rows: list[CsvImportPreviewRow] = []
    for index, row in enumerate(reader, start=2):
        name = (row.get("name") or "").strip()
        email = (row.get("email") or "").strip()
        institution = (row.get("institution") or "").strip()
        status = (row.get("status") or "SENT").strip().upper()
        error = None
        if not name:
            error = "Missing name."
        elif email:
            try:
                validate_email(email)
            except ValueError as exc:
                error = str(exc)
        elif status not in CandidateStatus.__members__:
            error = "Unknown status."
        rows.append(
            CsvImportPreviewRow(
                row_number=index,
                name=name,
                email=email,
                institution=institution,
                status=status,
                valid=error is None,
                error=error,
            ),
        )
    return rows


def import_contacted_csv(session: Session, csv_text: str) -> CsvImportResult:
    rows = preview_contacted_csv(csv_text)
    imported = 0
    skipped = 0
    errors: list[str] = []

    for row in rows:
        if not row.valid:
            skipped += 1
            errors.append(f"Row {row.row_number}: {row.error}")
            continue
        duplicate_warnings = detect_duplicate_warnings(
            session,
            full_name=row.name,
            institution=row.institution,
            email=row.email or None,
        )
        if duplicate_warnings:
            skipped += 1
            continue

        candidate = create_candidate(
            session,
            full_name=row.name,
            title=None,
            institution=row.institution or None,
            department=None,
            research_area=None,
            official_profile_url=None,
            notes="Imported from contacted-person CSV.",
        )
        if row.status in CandidateStatus.__members__:
            candidate.status = CandidateStatus[row.status]
        if row.email:
            add_email_address(
                session,
                candidate_id=candidate.id,
                email=row.email,
                source_url="contacted_people_csv",
                source_type="prior_contact_csv",
                confidence="MEDIUM",
                verification_status="IMPORTED",
            )
        imported += 1

    return CsvImportResult(imported=imported, skipped=skipped, errors=errors)
