from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.candidate import Candidate, CandidateStatus
from app.models.outreach import OutreachEventType
from app.models.paper import EvidenceClassification, EvidenceItem, PaperAnalysis, PaperFile
from app.services.candidates import record_event


def create_manual_analysis(
    session: Session,
    *,
    candidate: Candidate,
    paper_file: PaperFile,
    title: str,
    research_question: str,
    methods: str,
    results: str,
    connection_to_arnav: str,
    claim: str,
    evidence_text: str,
    page_number: int,
    section_name: str,
    classification: EvidenceClassification,
    confidence: float,
) -> PaperAnalysis:
    analysis = PaperAnalysis(
        candidate_id=candidate.id,
        paper_file_id=paper_file.id,
        title=title.strip(),
        research_question=research_question.strip(),
        methods=methods.strip(),
        results=results.strip(),
        connection_to_arnav=connection_to_arnav.strip(),
        confidence=confidence,
        provider="manual",
    )
    session.add(analysis)
    session.flush()
    evidence = EvidenceItem(
        analysis_id=analysis.id,
        claim=claim.strip(),
        evidence_text=evidence_text.strip(),
        page_number=page_number,
        section_name=section_name.strip() or "Unknown",
        classification=classification,
        confidence=confidence,
    )
    session.add(evidence)
    candidate.status = CandidateStatus.PAPER_ANALYZED
    record_event(
        session,
        candidate_id=candidate.id,
        event_type=OutreachEventType.ANALYSIS_ADDED,
        notes=f"Manual analysis added for {analysis.title}.",
    )
    return analysis


def list_analyses_for_paper(session: Session, paper_file_id: int) -> list[PaperAnalysis]:
    return list(
        session.scalars(
            select(PaperAnalysis)
            .where(PaperAnalysis.paper_file_id == paper_file_id)
            .order_by(PaperAnalysis.created_at.desc()),
        ),
    )


def get_analysis(session: Session, analysis_id: int) -> PaperAnalysis | None:
    return session.get(PaperAnalysis, analysis_id)


def evidence_for_analysis(session: Session, analysis_id: int) -> list[EvidenceItem]:
    return list(
        session.scalars(
            select(EvidenceItem)
            .where(EvidenceItem.analysis_id == analysis_id)
            .order_by(EvidenceItem.page_number.asc()),
        ),
    )
