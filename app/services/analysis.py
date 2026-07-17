from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.candidate import Candidate, CandidateStatus
from app.models.outreach import OutreachEventType
from app.models.paper import EvidenceClassification, EvidenceItem, PaperAnalysis, PaperFile
from app.services.candidates import record_event
from app.services.papers import read_parsed_text


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
        equations=None,
        computational_methods=None,
        datasets=None,
        software=None,
        assumptions=None,
        limitations=None,
        future_work=None,
        contribution_areas=None,
        candidate_role_notes=None,
        overclaim_risks=None,
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


def create_structured_analysis_from_text(
    session: Session,
    *,
    candidate: Candidate,
    paper_file: PaperFile,
    title: str,
    connection_to_arnav: str,
) -> PaperAnalysis:
    parsed_text = read_parsed_text(paper_file)
    sections = extract_structured_notes(parsed_text)
    primary_evidence = first_nonempty(
        sections["methods"],
        sections["results"],
        sections["limitations"],
        parsed_text[:500],
    )
    analysis = PaperAnalysis(
        candidate_id=candidate.id,
        paper_file_id=paper_file.id,
        title=title.strip(),
        research_question=sections["research_question"] or "Not clearly stated in extracted text.",
        methods=sections["methods"] or "Not clearly identified in extracted text.",
        results=sections["results"] or "Not clearly identified in extracted text.",
        equations=sections["equations"],
        computational_methods=sections["computational_methods"],
        datasets=sections["datasets"],
        software=sections["software"],
        assumptions=sections["assumptions"],
        limitations=sections["limitations"],
        future_work=sections["future_work"],
        contribution_areas=sections["contribution_areas"],
        candidate_role_notes=sections["candidate_role_notes"],
        overclaim_risks=sections["overclaim_risks"],
        connection_to_arnav=connection_to_arnav.strip(),
        confidence=0.65 if primary_evidence else 0.35,
        provider="deterministic-local-v1",
    )
    session.add(analysis)
    session.flush()
    session.add(
        EvidenceItem(
            analysis_id=analysis.id,
            claim=analysis.methods,
            evidence_text=primary_evidence[:700],
            page_number=page_number_for_evidence(primary_evidence),
            section_name="Extracted text",
            classification=EvidenceClassification.EXPLICIT,
            confidence=analysis.confidence,
        ),
    )
    candidate.status = CandidateStatus.PAPER_ANALYZED
    record_event(
        session,
        candidate_id=candidate.id,
        event_type=OutreachEventType.ANALYSIS_ADDED,
        notes=f"Local structured analysis added for {analysis.title}.",
    )
    return analysis


def first_nonempty(*values: str) -> str:
    return next((value for value in values if value.strip()), "")


def extract_structured_notes(text: str) -> dict[str, str]:
    lower = text.lower()
    return {
        "research_question": sentence_with_any(text, ["we study", "we investigate", "question"]),
        "methods": sentence_with_any(text, ["method", "simulation", "model", "algorithm"]),
        "equations": sentence_with_any(text, ["equation", "=", "∂", "sigma", "matrix"]),
        "computational_methods": sentence_with_any(
            text,
            ["simulation", "numerical", "algorithm", "computational"],
        ),
        "datasets": sentence_with_any(text, ["dataset", "survey", "catalog", "observations"]),
        "software": sentence_with_any(text, ["software", "code", "package", "python"]),
        "assumptions": sentence_with_any(text, ["assume", "assumption"]),
        "results": sentence_with_any(text, ["result", "we find", "we show"]),
        "limitations": sentence_with_any(text, ["limitation", "limited", "uncertain"]),
        "future_work": sentence_with_any(text, ["future work", "next", "further"]),
        "contribution_areas": contribution_categories(lower),
        "candidate_role_notes": "Candidate role requires metadata and manual review.",
        "overclaim_risks": (
            "Do not claim implementation, reproduction, or mastery without evidence."
        ),
    }


def sentence_with_any(text: str, needles: list[str]) -> str:
    normalized = " ".join(text.split())
    for sentence in normalized.split("."):
        lowered = sentence.lower()
        if any(needle in lowered for needle in needles):
            return sentence.strip()[:700]
    return ""


def contribution_categories(lowered_text: str) -> str:
    categories: list[str] = []
    if any(term in lowered_text for term in ["simulation", "numerical", "model"]):
        categories.append("numerical checks")
    if any(term in lowered_text for term in ["dataset", "survey", "observations"]):
        categories.append("data analysis")
    if any(term in lowered_text for term in ["software", "code", "python"]):
        categories.append("small software tools")
    if not categories:
        categories.append("careful literature review and validation")
    return ", ".join(categories)


def page_number_for_evidence(evidence: str) -> int:
    marker = "--- Page "
    if marker not in evidence:
        return 1
    try:
        return int(evidence.split(marker, maxsplit=1)[1].split(" ", maxsplit=1)[0])
    except (IndexError, ValueError):
        return 1


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
