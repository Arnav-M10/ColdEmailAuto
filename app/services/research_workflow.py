import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.candidate import Candidate, CandidateStatus
from app.models.draft import Draft
from app.models.paper import EvidenceClassification, EvidenceItem, PaperAnalysis, PaperFile
from app.models.publication import Authorship, Publication
from app.models.workflow import ResearchWorkflowRun
from app.services.ai_analysis import arnav_profile_summary, create_ai_analysis_from_text
from app.services.ai_providers import AIProvider, AIProviderError, get_ai_provider
from app.services.assets import required_attachments_ready
from app.services.drafting import generate_manual_draft
from app.services.metadata import (
    RECENT_YEAR_THRESHOLD,
    approve_publication_for_retrieval,
    list_candidate_publications,
    retrieve_recent_publications_for_candidate,
)
from app.services.retrieval import (
    PDFFetcherLike,
    plan_publication_pdf_retrieval,
    retrieve_publication_pdf,
)

WORKFLOW_STAGES = [
    "Finding publications",
    "Ranking papers",
    "Selecting paper",
    "Retrieving PDF",
    "Extracting text",
    "Analyzing paper",
    "Generating summary",
    "Generating email",
    "Ready for review",
]
ANALYSIS_PROMPT_VERSION = "paper-analysis-v1"


@dataclass(frozen=True)
class SelectionResult:
    authorship: Authorship | None
    publication: Publication | None
    reasons: list[str]
    rejected: list[dict[str, object]]
    metadata_only: Publication | None = None


def latest_workflow_run(session: Session, candidate_id: int) -> ResearchWorkflowRun | None:
    return session.scalars(
        select(ResearchWorkflowRun)
        .where(ResearchWorkflowRun.candidate_id == candidate_id)
        .order_by(ResearchWorkflowRun.created_at.desc()),
    ).first()


def run_research_workflow(
    session: Session,
    *,
    candidate: Candidate,
    provider: AIProvider | None = None,
    pdf_fetcher: PDFFetcherLike | None = None,
) -> ResearchWorkflowRun:
    workflow = ResearchWorkflowRun(candidate_id=candidate.id)
    session.add(workflow)
    session.flush()
    try:
        ensure_publications(session, candidate=candidate, workflow=workflow)
        set_stage(workflow, "Ranking papers")
        selection = select_best_publication(session, candidate=candidate)
        workflow.rejected_alternatives_json = json.dumps(selection.rejected)
        workflow.selection_reasons_json = json.dumps(selection.reasons)
        if selection.authorship is None or selection.publication is None:
            workflow.status = "FAILED"
            workflow.failed_stage = "Selecting paper"
            workflow.failure_reason = (
                "No suitable publication with lawful full text was available. "
                "The best metadata-only paper is shown for manual review."
            )
            if selection.metadata_only is not None:
                workflow.selected_publication_id = selection.metadata_only.id
            return workflow

        set_stage(workflow, "Selecting paper")
        workflow.selected_publication_id = selection.publication.id
        workflow.selection_score = selection.authorship.score
        workflow.selected_at = datetime.now(UTC)
        approve_publication_for_retrieval(
            session,
            candidate_id=candidate.id,
            publication_id=selection.publication.id,
            notes="Automatically selected by outreach ranking.",
        )

        set_stage(workflow, "Retrieving PDF")
        paper_file = retrieve_selected_pdf(
            session,
            candidate=candidate,
            publication=selection.publication,
            workflow=workflow,
            pdf_fetcher=pdf_fetcher,
        )
        workflow.paper_file_id = paper_file.id

        set_stage(workflow, "Extracting text")
        if not paper_file.parsed_text_path:
            raise WorkflowStageError("Extracting text", "PDF text extraction did not produce text.")

        set_stage(workflow, "Analyzing paper")
        analysis = get_or_create_analysis(
            session,
            candidate=candidate,
            paper_file=paper_file,
            publication=selection.publication,
            provider=provider,
        )
        workflow.analysis_id = analysis.id
        session.flush()

        set_stage(workflow, "Generating summary")
        evidence = explicit_evidence_for_analysis(session, analysis.id)
        if not evidence:
            raise WorkflowStageError(
                "Generating summary",
                "No explicit evidence was available for paper-specific drafting.",
            )

        set_stage(workflow, "Generating email")
        if not required_attachments_ready():
            raise WorkflowStageError(
                "Generating email",
                "Required resume and research portfolio PDFs must be present and valid "
                "before a draft can be marked ready for review.",
            )
        draft = get_or_create_draft(
            session,
            candidate=candidate,
            analysis=analysis,
            evidence=evidence[0],
        )
        session.flush()
        workflow.draft_id = draft.id
        workflow.current_stage = "Ready for review"
        workflow.status = "READY_FOR_REVIEW"
        candidate.status = CandidateStatus.DRAFT_READY
    except WorkflowStageError as exc:
        fail_workflow(workflow, exc.stage, exc.reason)
    except (AIProviderError, ValueError) as exc:
        fail_workflow(workflow, workflow.current_stage, str(exc))
    return workflow


def ensure_publications(
    session: Session,
    *,
    candidate: Candidate,
    workflow: ResearchWorkflowRun,
) -> None:
    set_stage(workflow, "Finding publications")
    if list_candidate_publications(session, candidate.id):
        return
    if not candidate.openalex_author_id:
        raise WorkflowStageError(
            "Finding publications",
            "OpenAlex author identity must be confirmed before running the workflow.",
        )
    retrieve_recent_publications_for_candidate(session, candidate=candidate)


def select_best_publication(session: Session, *, candidate: Candidate) -> SelectionResult:
    rows = list_candidate_publications(session, candidate.id, sort="best")
    rejected: list[dict[str, object]] = []
    metadata_only: Publication | None = rows[0][1] if rows else None
    for authorship, publication in rows:
        reasons = suitability_rejections(authorship, publication)
        if reasons:
            rejected.append(
                {
                    "publication_id": publication.id,
                    "title": publication.title,
                    "score": authorship.score,
                    "reasons": reasons,
                },
            )
            continue
        return SelectionResult(
            authorship=authorship,
            publication=publication,
            reasons=selection_reasons(authorship, publication),
            rejected=rejected,
            metadata_only=metadata_only,
        )
    return SelectionResult(
        authorship=None,
        publication=None,
        reasons=[],
        rejected=rejected,
        metadata_only=metadata_only,
    )


def suitability_rejections(authorship: Authorship, publication: Publication) -> list[str]:
    reasons: list[str] = []
    warnings = _json_list(authorship.warnings_json)
    if not authorship.confirmed_author_present:
        reasons.append("Confirmed candidate authorship was not found.")
    if publication.year is None or publication.year < RECENT_YEAR_THRESHOLD:
        reasons.append("Publication is not recent enough.")
    components = _score_components(authorship)
    if components.get("portfolio_similarity", 0.0) < 8.0:
        reasons.append("Portfolio fit is too weak for automatic analysis.")
    if plan_publication_pdf_retrieval(publication) is None:
        reasons.append("No lawful full text is available.")
    if authorship.author_count and authorship.author_count > 25:
        reasons.append("Author list is too large for automatic selection.")
    if authorship.role not in {"first_author", "last_author", "corresponding_author"}:
        reasons.append("Candidate is not first, last, or corresponding author.")
    if any("large author list" in str(warning).lower() for warning in warnings):
        reasons.append("Large-authorship warning requires manual review.")
    if disallowed_publication_type(publication):
        reasons.append("Publication type is not suitable for automatic outreach.")
    return reasons


def disallowed_publication_type(publication: Publication) -> bool:
    text = f"{publication.title} {publication.work_type or ''}".lower()
    blocked = [
        "correction",
        "editorial",
        "conference notice",
        "erratum",
        "dataset",
        "data descriptor",
    ]
    return any(term in text for term in blocked)


def selection_reasons(authorship: Authorship, publication: Publication) -> list[str]:
    reasons = _score_reasons(authorship)
    reasons.insert(0, f"Highest suitable outreach score: {authorship.score:.0f}.")
    if publication.pdf_url or publication.arxiv_id or publication.open_access_url:
        reasons.append("Lawful full text source was available.")
    return reasons


def retrieve_selected_pdf(
    session: Session,
    *,
    candidate: Candidate,
    publication: Publication,
    workflow: ResearchWorkflowRun,
    pdf_fetcher: PDFFetcherLike | None = None,
) -> PaperFile:
    try:
        paper_file = retrieve_publication_pdf(
            session,
            candidate=candidate,
            publication=publication,
            fetcher=pdf_fetcher,
        )
    except ValueError as exc:
        workflow.retrieval_result_json = json.dumps({"status": "failed", "error": str(exc)})
        raise WorkflowStageError("Retrieving PDF", str(exc)) from exc
    workflow.retrieval_result_json = json.dumps(
        {
            "status": "retrieved",
            "source_url": paper_file.source_url,
            "license_note": paper_file.license_note,
            "sha256": paper_file.sha256,
            "page_count": paper_file.page_count,
        },
    )
    return paper_file


def get_or_create_analysis(
    session: Session,
    *,
    candidate: Candidate,
    paper_file: PaperFile,
    publication: Publication,
    provider: AIProvider | None,
) -> PaperAnalysis:
    selected_provider = provider or get_ai_provider()
    provider_key = f"{selected_provider.name}:{selected_provider.model}:{ANALYSIS_PROMPT_VERSION}"
    cached = session.scalars(
        select(PaperAnalysis).where(
            PaperAnalysis.paper_file_id == paper_file.id,
            PaperAnalysis.provider == provider_key,
        ),
    ).first()
    if cached is not None:
        return cached
    analysis = create_ai_analysis_from_text(
        session,
        candidate=candidate,
        paper_file=paper_file,
        title=publication.title,
        connection_to_arnav="; ".join(
            _score_reasons_for_publication(session, candidate.id, publication.id),
        ),
        profile_summary=arnav_profile_summary(),
        provider=selected_provider,
    )
    analysis.provider = provider_key
    return analysis


def get_or_create_draft(
    session: Session,
    *,
    candidate: Candidate,
    analysis: PaperAnalysis,
    evidence: EvidenceItem,
) -> Draft:
    generation_version = f"auto-workflow-v1:analysis:{analysis.id}"
    existing = session.scalars(
        select(Draft)
        .where(
            Draft.candidate_id == candidate.id,
            Draft.generation_version == generation_version,
        )
        .order_by(Draft.created_at.desc()),
    ).first()
    if existing is not None:
        return existing
    draft = generate_manual_draft(
        session,
        candidate=candidate,
        analysis=analysis,
        evidence=evidence,
    )
    draft.generation_version = generation_version
    return draft


def explicit_evidence_for_analysis(session: Session, analysis_id: int) -> list[EvidenceItem]:
    evidence = session.scalars(
        select(EvidenceItem)
        .where(EvidenceItem.analysis_id == analysis_id)
        .order_by(EvidenceItem.page_number.asc()),
    )
    return [
        item
        for item in evidence
        if str(item.classification).split(".")[-1] == EvidenceClassification.EXPLICIT.value
    ]


def workflow_review_context(
    session: Session,
    *,
    workflow: ResearchWorkflowRun | None,
) -> dict[str, object]:
    if workflow is None:
        return {}
    return {
        "workflow": workflow,
        "workflow_selection_reasons": _json_list(workflow.selection_reasons_json),
        "workflow_rejected_alternatives": _json_list(workflow.rejected_alternatives_json),
        "workflow_retrieval_result": _json_object(workflow.retrieval_result_json),
        "attachments_ready": required_attachments_ready(),
    }


def set_stage(workflow: ResearchWorkflowRun, stage: str) -> None:
    workflow.current_stage = stage


def fail_workflow(workflow: ResearchWorkflowRun, stage: str, reason: str) -> None:
    workflow.status = "FAILED"
    workflow.failed_stage = stage
    workflow.failure_reason = reason
    workflow.current_stage = stage


def _score_components(authorship: Authorship) -> dict[str, float]:
    details = _json_object(authorship.score_details_json)
    raw_components = details.get("components", {})
    if not isinstance(raw_components, dict):
        return {}
    return {str(key): float(value) for key, value in raw_components.items()}


def _score_reasons(authorship: Authorship) -> list[str]:
    details = _json_object(authorship.score_details_json)
    raw_reasons = details.get("reasons", [])
    return [str(reason) for reason in raw_reasons] if isinstance(raw_reasons, list) else []


def _score_reasons_for_publication(
    session: Session,
    candidate_id: int,
    publication_id: int,
) -> list[str]:
    authorship = session.scalars(
        select(Authorship).where(
            Authorship.candidate_id == candidate_id,
            Authorship.publication_id == publication_id,
        ),
    ).first()
    return _score_reasons(authorship) if authorship else []


def _json_list(value: str) -> list[object]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _json_object(value: str) -> dict[str, object]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


class WorkflowStageError(ValueError):
    def __init__(self, stage: str, reason: str) -> None:
        super().__init__(reason)
        self.stage = stage
        self.reason = reason
