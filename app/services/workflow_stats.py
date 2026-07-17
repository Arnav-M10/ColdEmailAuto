from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Executable

from app.models.candidate import Candidate, CandidateStatus
from app.models.discovery import DepartmentImport, DepartmentImportStatus, DiscoveryCandidate
from app.models.draft import Draft
from app.models.email_address import EmailAddress
from app.models.paper import PaperAnalysis, PaperFile
from app.models.publication import Authorship, Publication


@dataclass(frozen=True)
class WorkflowMetric:
    label: str
    value: int
    note: str


def count_scalar(session: Session, statement: Executable) -> int:
    value = session.scalar(statement)
    return int(value or 0)


def dashboard_metrics(session: Session) -> list[WorkflowMetric]:
    missing_email = count_scalar(
        session,
        select(func.count(Candidate.id))
        .outerjoin(EmailAddress, Candidate.id == EmailAddress.candidate_id)
        .where(Candidate.deleted_at.is_(None), EmailAddress.id.is_(None)),
    )
    failures = count_scalar(
        session,
        select(func.count(DepartmentImport.id)).where(
            DepartmentImport.status == DepartmentImportStatus.EXTRACTION_FAILED,
        ),
    )
    return [
        WorkflowMetric(
            "Departments imported",
            count_scalar(session, select(func.count(DepartmentImport.id))),
            "Official pages fetched through the safe retrieval boundary.",
        ),
        WorkflowMetric(
            "Candidates discovered",
            count_scalar(session, select(func.count(DiscoveryCandidate.id))),
            "Review previews created from approved directories.",
        ),
        WorkflowMetric(
            "Candidates excluded",
            count_scalar(
                session,
                select(func.count(DiscoveryCandidate.id)).where(
                    DiscoveryCandidate.screening_status == "EXCLUDED",
                    DiscoveryCandidate.override_exclusion.is_(False),
                ),
            ),
            "Default exclusions still visible for manual override.",
        ),
        WorkflowMetric(
            "Candidates shortlisted",
            count_scalar(
                session,
                select(func.count(Candidate.id)).where(
                    Candidate.deleted_at.is_(None),
                    Candidate.status == CandidateStatus.SHORTLISTED,
                ),
            ),
            "Saved candidates marked for publication review.",
        ),
        WorkflowMetric(
            "Papers found",
            count_scalar(session, select(func.count(Publication.id))),
            "Publication metadata stored locally.",
        ),
        WorkflowMetric(
            "Papers selected",
            count_scalar(session, select(func.count(Authorship.id)).where(Authorship.score >= 60)),
            "Candidate-paper links with a strong local fit score.",
        ),
        WorkflowMetric(
            "PDFs retrieved",
            count_scalar(session, select(func.count(PaperFile.id))),
            "Validated lawful PDFs stored locally.",
        ),
        WorkflowMetric(
            "Papers analyzed",
            count_scalar(session, select(func.count(PaperAnalysis.id))),
            "Paper analyses with evidence records.",
        ),
        WorkflowMetric(
            "Drafts awaiting review",
            count_scalar(
                session,
                select(func.count(Draft.id)).where(Draft.approved_by_user.is_(False)),
            ),
            "Generated or manual drafts not approved yet.",
        ),
        WorkflowMetric("Missing email", missing_email, "Saved candidates without an email record."),
        WorkflowMetric(
            "Missing full text",
            count_scalar(
                session,
                select(func.count(Candidate.id)).where(
                    Candidate.status == CandidateStatus.NO_FULL_TEXT,
                ),
            ),
            "Candidates blocked because no lawful full text is available.",
        ),
        WorkflowMetric("Failures", failures, "Imports or retrievals that need review."),
    ]
