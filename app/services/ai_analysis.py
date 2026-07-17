from sqlalchemy.orm import Session

from app.models.candidate import Candidate, CandidateStatus
from app.models.outreach import OutreachEventType
from app.models.paper import EvidenceItem, PaperAnalysis, PaperFile
from app.services.ai_providers import AIProvider, PaperAnalysisRequest, get_ai_provider
from app.services.candidates import record_event
from app.services.papers import read_parsed_text


def create_ai_analysis_from_text(
    session: Session,
    *,
    candidate: Candidate,
    paper_file: PaperFile,
    title: str,
    connection_to_arnav: str,
    profile_summary: str,
    provider: AIProvider | None = None,
) -> PaperAnalysis:
    parsed_text = read_parsed_text(paper_file)
    if not parsed_text.strip():
        raise ValueError("No parsed paper text is available for AI analysis.")
    selected_provider = provider or get_ai_provider()
    output = selected_provider.analyze_paper(
        PaperAnalysisRequest(
            paper_title=title.strip(),
            paper_text=parsed_text,
            profile_summary=profile_summary.strip(),
            connection_context=connection_to_arnav.strip(),
        ),
    )
    analysis = PaperAnalysis(
        candidate_id=candidate.id,
        paper_file_id=paper_file.id,
        title=output.title,
        research_question=output.research_question,
        methods=output.methods,
        results=output.results,
        equations=output.equations,
        computational_methods=join_optional(output.computational_methods, output.numerical_methods),
        datasets=output.datasets,
        software=output.software,
        assumptions=output.assumptions,
        limitations=output.limitations,
        future_work=output.future_work,
        contribution_areas=output.contribution_areas,
        candidate_role_notes=output.candidate_role_notes,
        overclaim_risks=output.overclaim_risks,
        connection_to_arnav=output.connection_to_arnav,
        confidence=output.confidence,
        provider=f"{selected_provider.name}:{selected_provider.model}",
    )
    session.add(analysis)
    session.flush()
    for item in output.evidence:
        session.add(
            EvidenceItem(
                analysis_id=analysis.id,
                claim=item.claim,
                evidence_text=item.evidence_text,
                page_number=item.page_number,
                section_name=item.section_name,
                classification=item.classification,
                confidence=item.confidence,
            ),
        )
    candidate.status = CandidateStatus.PAPER_ANALYZED
    record_event(
        session,
        candidate_id=candidate.id,
        event_type=OutreachEventType.ANALYSIS_ADDED,
        notes=f"AI analysis added for {analysis.title} using {analysis.provider}.",
    )
    return analysis


def join_optional(*values: str | None) -> str | None:
    joined = "; ".join(value.strip() for value in values if value and value.strip())
    return joined or None


def arnav_profile_summary() -> str:
    return (
        "Arnav Mittal is an incoming TAMS student at the University of North Texas. "
        "Relevant work includes Regge calculus and spectral geometry; Parker Solar Probe "
        "magnetic-field time-series analysis with persistent homology and scientific Python; "
        "asteroid orbit determination with Monte Carlo uncertainty propagation; and stochastic "
        "optimization with convex modeling and numerical uncertainty."
    )
