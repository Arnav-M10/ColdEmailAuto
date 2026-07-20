import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.session import is_sqlite_lock_error
from app.models.candidate import Candidate, CandidateStatus
from app.models.draft import Draft
from app.models.intelligence import ResearcherProfile
from app.models.paper import EvidenceClassification, EvidenceItem, PaperAnalysis, PaperFile
from app.models.publication import Authorship, Publication
from app.models.workflow import ResearchWorkflowRun
from app.services.ai_analysis import arnav_profile_summary, create_ai_analysis_from_text
from app.services.ai_providers import AIProvider, AIProviderError, AIRateLimitError, get_ai_provider
from app.services.ai_usage import (
    AIRequestLimitError,
    assert_ai_request_allowed,
    record_ai_request,
)
from app.services.assets import required_attachments_ready
from app.services.drafting import generate_manual_draft
from app.services.email_discovery import ensure_verified_official_email
from app.services.metadata import (
    RECENT_YEAR_THRESHOLD,
    approve_publication_for_retrieval,
    list_candidate_publications,
    load_research_portfolio_text_status,
    retrieve_recent_publications_for_candidate,
)
from app.services.research_intelligence import (
    EmailUsefulness,
    build_or_reuse_researcher_profile,
    email_usefulness_for_publication,
    latest_researcher_profile,
    profile_view,
)
from app.services.retrieval import (
    PDFEligibility,
    PDFFetcherLike,
    pdf_eligibility_for_publication,
    retrieve_publication_pdf,
)
from app.services.review import manual_review_context

WORKFLOW_STAGES = [
    "Finding publications",
    "Understanding researcher",
    "Ranking papers",
    "Selecting paper",
    "Retrieving PDF",
    "Extracting text",
    "Analyzing paper",
    "Generating summary",
    "Generating email",
    "Verifying official email",
    "Verifying attachments",
    "Ready for review",
]
ANALYSIS_PROMPT_VERSION = "paper-analysis-v1"
AUTOMATIC_SELECTION_TIE_EPSILON = 0.01
MIN_AUTOMATIC_PUBLICATION_SCORE = 40.0
PUBLICATION_SELECTION_WORKFLOW_REASONS = {
    "automatic_selection_tie",
    "ranking_exhausted",
}
logger = logging.getLogger("professor_outreach.workflow")


@dataclass(frozen=True)
class SelectionResult:
    authorship: Authorship | None
    publication: Publication | None
    reasons: list[str]
    rejected: list[dict[str, object]]
    score: float = 0.0
    metadata_only: Publication | None = None


@dataclass(frozen=True)
class RankedPublicationSelection:
    authorship: Authorship
    publication: Publication
    reasons: list[str]
    score: float
    rank: int
    pdf_eligibility: PDFEligibility


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
    workflow: ResearchWorkflowRun | None = None,
    commit_checkpoints: bool = False,
) -> ResearchWorkflowRun:
    if workflow is None:
        workflow = ResearchWorkflowRun(candidate_id=candidate.id)
        session.add(workflow)
        session.flush()
    else:
        prepare_workflow_for_resume(workflow)
    workflow.status = "RUNNING"
    commit_workflow_checkpoint(session, enabled=commit_checkpoints)
    try:
        ensure_publications(session, candidate=candidate, workflow=workflow)
        if workflow.status == "WAITING_FOR_AUTHOR_CONFIRMATION":
            commit_workflow_checkpoint(session, enabled=commit_checkpoints)
            return workflow
        commit_workflow_checkpoint(session, enabled=commit_checkpoints)
        portfolio_status = load_research_portfolio_text_status()
        if not portfolio_status.available:
            wait_for_portfolio_input(workflow, portfolio_status.reason)
            commit_workflow_checkpoint(session, enabled=commit_checkpoints)
            return workflow
        set_stage(workflow, "Understanding researcher")
        profile = build_or_reuse_researcher_profile(session, candidate=candidate)
        workflow.researcher_profile_id = profile.id
        commit_workflow_checkpoint(session, enabled=commit_checkpoints)

        set_stage(workflow, "Ranking papers")
        ranked_selections, rejected, metadata_only = ranked_publication_selections(
            session,
            candidate=candidate,
        )
        workflow.rejected_alternatives_json = json.dumps(rejected)
        if not ranked_selections:
            workflow.status = "FAILED"
            workflow.failed_stage = None
            workflow.failure_reason = (
                "No publication had a lawful retrievable PDF for the automatic workflow."
            )
            workflow.selected_publication_id = None
            workflow.retrieval_result_json = json.dumps(
                {
                    "status": "ranking_exhausted",
                    "reviewed_publications": len(rejected),
                    "attempts": [],
                    "rejected_publications": rejected,
                    "remaining_alternatives": 0,
                },
            )
            if metadata_only is not None:
                workflow.rejected_alternatives_json = json.dumps(
                    [
                        *rejected,
                        {
                            "publication_id": metadata_only.id,
                            "title": metadata_only.title,
                            "rank": 1,
                            "reasons": ["Highest-ranked metadata-only paper retained for review."],
                        },
                    ],
                )
            commit_workflow_checkpoint(session, enabled=commit_checkpoints)
            return workflow
        if automatic_selection_tie(ranked_selections):
            logger.info(
                "automatic_selection_tie_continuing_with_top_ranked",
                extra={
                    "candidate_id": candidate.id,
                    "publication_id": ranked_selections[0].publication.id,
                    "total_score": ranked_selections[0].score,
                },
            )

        paper_file: PaperFile | None = None
        selected_publication: Publication | None = None
        selected_selection: RankedPublicationSelection | None = None
        attempts: list[dict[str, object]] = []
        for selection in ranked_selections:
            set_stage(workflow, "Selecting paper")
            workflow.selected_publication_id = selection.publication.id
            workflow.selection_score = selection.score
            workflow.selected_at = datetime.now(UTC)
            workflow.selection_reasons_json = json.dumps(selection.reasons)
            approve_publication_for_retrieval(
                session,
                candidate_id=candidate.id,
                publication_id=selection.publication.id,
                notes="Automatically selected by outreach ranking.",
            )
            log_workflow_transition(
                workflow,
                from_stage="Ranking papers",
                to_stage="Retrieving PDF",
                publication=selection.publication,
                selection=selection,
            )
            commit_workflow_checkpoint(session, enabled=commit_checkpoints)

            set_stage(workflow, "Retrieving PDF")
            try:
                paper_file = retrieve_selected_pdf(
                    session,
                    candidate=candidate,
                    publication=selection.publication,
                    workflow=workflow,
                    pdf_fetcher=pdf_fetcher,
                )
            except WorkflowStageError as exc:
                attempt = retrieval_attempt_record(
                    selection=selection,
                    attempted=True,
                    status="failed",
                    rejection_reason=exc.reason,
                )
                attempts.append(attempt)
                rejected.append(attempt)
                workflow.rejected_alternatives_json = json.dumps(rejected)
                workflow.retrieval_result_json = json.dumps(
                    {
                        "status": "trying_next_suitable_paper",
                        "attempts": attempts,
                        "latest_failure": exc.reason,
                    },
                )
                workflow.selected_publication_id = None
                log_workflow_transition(
                    workflow,
                    from_stage="Retrieving PDF",
                    to_stage="Selecting next paper",
                    publication=selection.publication,
                    selection=selection,
                    exception=exc,
                    reason=exc.reason,
                )
                commit_workflow_checkpoint(session, enabled=commit_checkpoints)
                continue
            attempts.append(
                retrieval_attempt_record(
                    selection=selection,
                    attempted=True,
                    status="retrieved",
                    rejection_reason=None,
                ),
            )
            selected_publication = selection.publication
            selected_selection = selection
            break

        if paper_file is None or selected_publication is None or selected_selection is None:
            workflow.status = "FAILED"
            workflow.failed_stage = None
            workflow.current_stage = "Selecting next paper"
            workflow.failure_reason = (
                "All automatically suitable publications failed lawful PDF retrieval. "
                "The one-button workflow tried each ranked candidate paper without opening "
                "manual selection."
            )
            workflow.selected_publication_id = None
            workflow.retrieval_result_json = json.dumps(
                {
                    "status": "all_suitable_papers_exhausted",
                    "attempts": attempts,
                    "remaining_alternatives": 0,
                },
            )
            commit_workflow_checkpoint(session, enabled=commit_checkpoints)
            return workflow

        workflow.retrieval_result_json = json.dumps(
            {
                "status": "retrieved",
                "attempts": attempts,
                "paper_file_id": paper_file.id,
                "source_url": paper_file.source_url,
                "license_note": paper_file.license_note,
                "sha256": paper_file.sha256,
                "page_count": paper_file.page_count,
            },
        )
        workflow.selection_reasons_json = json.dumps(selected_selection.reasons)
        workflow.selected_publication_id = selected_publication.id
        workflow.selection_score = selected_selection.score
        workflow.paper_file_id = paper_file.id
        commit_workflow_checkpoint(session, enabled=commit_checkpoints)

        set_stage(workflow, "Extracting text")
        if not paper_file.parsed_text_path:
            raise WorkflowStageError("Extracting text", "PDF text extraction did not produce text.")

        set_stage(workflow, "Analyzing paper")
        analysis = get_or_create_analysis(
            session,
            candidate=candidate,
            paper_file=paper_file,
            publication=selected_publication,
            provider=provider,
            workflow=workflow,
            commit_checkpoints=commit_checkpoints,
        )
        workflow.analysis_id = analysis.id
        session.flush()
        commit_workflow_checkpoint(session, enabled=commit_checkpoints)

        set_stage(workflow, "Generating summary")
        evidence = explicit_evidence_for_analysis(session, analysis.id)
        if not evidence:
            raise WorkflowStageError(
                "Generating summary",
                "No explicit evidence was available for paper-specific drafting.",
            )
        workflow.summary_json = json.dumps(
            {
                "what_the_paper_is_about": analysis.research_question,
                "what_the_researcher_did": analysis.methods,
                "what_they_found": analysis.results,
                "connection_to_arnav": analysis.connection_to_arnav,
                "realistic_help": "coding, data analysis, numerical checks, or visualization",
                "avoid_claiming": (
                    analysis.overclaim_risks or "Do not claim independent verification."
                ),
                "best_supported_detail": evidence[0].claim,
            },
        )

        set_stage(workflow, "Generating email")
        set_stage(workflow, "Verifying official email")
        if ensure_verified_official_email(session, candidate=candidate) is None:
            candidate.status = CandidateStatus.NO_VERIFIED_EMAIL
            raise WorkflowStageError(
                "Verifying official email",
                "MISSING_OFFICIAL_EMAIL: a verified official email is required before review.",
            )
        set_stage(workflow, "Verifying attachments")
        if not required_attachments_ready():
            raise WorkflowStageError(
                "Verifying attachments",
                "Required resume and research portfolio PDFs must be present and valid "
                "before a draft can be marked ready for review.",
            )
        set_stage(workflow, "Generating email")
        draft = get_or_create_draft(
            session,
            candidate=candidate,
            analysis=analysis,
            evidence=evidence[0],
        )
        session.flush()
        workflow.draft_id = draft.id
        review = manual_review_context(session, draft=draft)
        workflow.claim_check_json = json.dumps(review.sentence_checks)
        if review.approval_errors:
            raise WorkflowStageError("Generating email", "; ".join(review.approval_errors))
        workflow.current_stage = "Ready for review"
        workflow.status = "READY_FOR_REVIEW"
        candidate.status = CandidateStatus.DRAFT_READY
        commit_workflow_checkpoint(session, enabled=commit_checkpoints)
    except WorkflowStageError as exc:
        fail_workflow(workflow, exc.stage, exc.reason)
    except AIRateLimitError:
        workflow.status = "SKIPPED_PROVIDER_RATE_LIMIT"
        workflow.failed_stage = None
        workflow.failure_reason = (
            "AI provider rate limit persisted after retries; the outreach agent will try "
            "the next candidate."
        )
    except (AIProviderError, AIRequestLimitError, ValueError) as exc:
        fail_workflow(workflow, workflow.current_stage, str(exc))
    except OperationalError as exc:
        if is_sqlite_lock_error(exc):
            raise
        fail_workflow(workflow, workflow.current_stage, str(exc))
    except Exception as exc:
        fail_workflow(
            workflow,
            workflow.current_stage,
            f"Unexpected workflow error ({exc.__class__.__name__}): {exc}",
        )
    commit_workflow_checkpoint(session, enabled=commit_checkpoints)
    return workflow


def should_display_workflow(workflow: ResearchWorkflowRun | None) -> bool:
    if workflow is None:
        return False
    if workflow.status != "WAITING_FOR_MANUAL_PAPER_SELECTION":
        return True
    if (
        workflow.selected_publication_id
        or workflow.paper_file_id
        or workflow.analysis_id
        or workflow.draft_id
        or workflow.ai_request_count
    ):
        return True
    retrieval_result = _json_object(workflow.retrieval_result_json)
    return bool(retrieval_result.get("status"))


def workflow_should_open_publication_selection(workflow: ResearchWorkflowRun) -> bool:
    if workflow.status != "WAITING_FOR_MANUAL_PAPER_SELECTION":
        return False
    retrieval_result = _json_object(workflow.retrieval_result_json)
    return str(retrieval_result.get("status")) in PUBLICATION_SELECTION_WORKFLOW_REASONS


def ensure_publications(
    session: Session,
    *,
    candidate: Candidate,
    workflow: ResearchWorkflowRun,
) -> None:
    set_stage(workflow, "Finding publications")
    if not candidate.openalex_author_id:
        workflow.status = "WAITING_FOR_AUTHOR_CONFIRMATION"
        workflow.failed_stage = None
        workflow.failure_reason = (
            "Confirm the OpenAlex author profile before the workflow retrieves publications."
        )
        return
    existing_publications = list_candidate_publications(session, candidate.id)
    portfolio_status = load_research_portfolio_text_status()
    if existing_publications and not publication_scores_need_portfolio_refresh(
        session,
        candidate.id,
        portfolio_available=portfolio_status.available,
    ):
        return
    retrieve_recent_publications_for_candidate(session, candidate=candidate)


def publication_scores_need_portfolio_refresh(
    session: Session,
    candidate_id: int,
    *,
    portfolio_available: bool,
) -> bool:
    if not portfolio_available:
        return False
    authorships = session.scalars(
        select(Authorship).where(Authorship.candidate_id == candidate_id),
    )
    for authorship in authorships:
        warnings = _json_list(authorship.warnings_json)
        if any(str(warning).startswith("PORTFOLIO_INPUT_UNAVAILABLE") for warning in warnings):
            return True
        if "portfolio_similarity" not in _score_components(authorship):
            return True
    return False


def select_best_publication(session: Session, *, candidate: Candidate) -> SelectionResult:
    suitable, rejected, metadata_only = ranked_publication_selections(session, candidate=candidate)
    if suitable:
        selected = suitable[0]
        return SelectionResult(
            authorship=selected.authorship,
            publication=selected.publication,
            reasons=selected.reasons,
            rejected=rejected,
            score=selected.score,
            metadata_only=metadata_only,
        )
    return SelectionResult(
        authorship=None,
        publication=None,
        reasons=[],
        rejected=rejected,
        score=0.0,
        metadata_only=metadata_only,
    )


def automatic_selection_tie(selections: list[RankedPublicationSelection]) -> bool:
    return (
        len(selections) > 1
        and abs(selections[0].score - selections[1].score) <= AUTOMATIC_SELECTION_TIE_EPSILON
    )


def ranked_publication_selections(
    session: Session,
    *,
    candidate: Candidate,
) -> tuple[list[RankedPublicationSelection], list[dict[str, object]], Publication | None]:
    rows = list_candidate_publications(session, candidate.id, sort="best")
    rejected: list[dict[str, object]] = []
    metadata_only: Publication | None = rows[0][1] if rows else None
    profile = latest_researcher_profile(session, candidate.id)
    scored_rows = []
    for authorship, publication in rows:
        usefulness = email_usefulness_for_publication(
            publication=publication,
            authorship=authorship,
            profile=profile,
        )
        scored_rows.append(
            (authorship.score + usefulness.score, authorship, publication, usefulness),
        )
    suitable: list[RankedPublicationSelection] = []
    for rank, (score, authorship, publication, usefulness) in enumerate(
        sorted(
            scored_rows,
            key=lambda item: item[0],
            reverse=True,
        ),
        start=1,
    ):
        eligibility = pdf_eligibility_for_publication(publication)
        reasons = suitability_rejections(
            authorship,
            publication,
            pdf_eligibility=eligibility,
        )
        reasons.extend(usefulness.rejections)
        if reasons:
            rejected_selection = RankedPublicationSelection(
                authorship=authorship,
                publication=publication,
                reasons=[],
                score=score,
                rank=rank,
                pdf_eligibility=eligibility,
            )
            rejection_record = {
                **retrieval_attempt_record(
                    selection=rejected_selection,
                    attempted=False,
                    status="rejected_before_retrieval",
                    rejection_reason="; ".join(reasons),
                ),
                "reasons": reasons,
            }
            log_publication_rejection(
                candidate=candidate,
                selection=rejected_selection,
                reasons=reasons,
            )
            rejected.append(rejection_record)
            continue
        suitable.append(
            RankedPublicationSelection(
                authorship=authorship,
                publication=publication,
                reasons=selection_reasons(authorship, publication, usefulness, eligibility),
                score=score,
                rank=rank,
                pdf_eligibility=eligibility,
            ),
        )
    return suitable, rejected, metadata_only


def suitability_rejections(
    authorship: Authorship,
    publication: Publication,
    *,
    pdf_eligibility: PDFEligibility | None = None,
) -> list[str]:
    reasons: list[str] = []
    warnings = _json_list(authorship.warnings_json)
    if not authorship.confirmed_author_present:
        reasons.append("Confirmed candidate authorship was not found.")
    if publication.year is None or publication.year < RECENT_YEAR_THRESHOLD:
        reasons.append("Publication is not recent enough.")
    if any(str(warning).startswith("PORTFOLIO_INPUT_UNAVAILABLE") for warning in warnings):
        reasons.append("Portfolio input is unavailable, so automatic ranking is blocked.")
    eligibility = pdf_eligibility or pdf_eligibility_for_publication(publication)
    if not eligibility.eligible:
        reasons.append(eligibility.rejection_reason or "No lawful full text is available.")
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


def selection_reasons(
    authorship: Authorship,
    publication: Publication,
    usefulness: EmailUsefulness,
    pdf_eligibility: PDFEligibility | None = None,
) -> list[str]:
    reasons = _score_reasons(authorship)
    reasons.insert(0, f"Highest suitable outreach score: {authorship.score:.0f}.")
    eligibility = pdf_eligibility or pdf_eligibility_for_publication(publication)
    if eligibility.eligible:
        reasons.append(f"Lawful full text source was available: {eligibility.source_type}.")
    reasons.append(f"Email usefulness score: {usefulness.score:.0f}.")
    reasons.extend(usefulness.reasons)
    return reasons


def retrieval_attempt_record(
    *,
    selection: RankedPublicationSelection,
    attempted: bool,
    status: str,
    rejection_reason: str | None,
) -> dict[str, object]:
    components = _score_components(selection.authorship)
    eligibility = selection.pdf_eligibility
    return {
        "publication_id": selection.publication.id,
        "title": selection.publication.title,
        "rank": selection.rank,
        "selection_score": round(selection.score, 2),
        "portfolio_similarity": components.get("portfolio_similarity"),
        "pdf_eligibility_type": eligibility.source_type,
        "canonical_pdf_url": eligibility.canonical_pdf_url,
        "canonical_pdf_url_host": url_host(eligibility.canonical_pdf_url),
        "landing_page_url": eligibility.landing_page_url,
        "lawful_source_reason": eligibility.lawful_source_reason,
        "retrieval_priority": eligibility.retrieval_priority,
        "retrieval_attempted": attempted,
        "retrieval_status": status,
        "content_type": None,
        "size": None,
        "validation_result": "not_attempted" if not attempted else status,
        "rejection_reason": rejection_reason or eligibility.rejection_reason,
    }


def log_publication_rejection(
    *,
    candidate: Candidate,
    selection: RankedPublicationSelection,
    reasons: list[str],
) -> None:
    logger.info(
        "Publication rejected from automatic workflow: %s",
        "; ".join(reasons),
        extra={
            "candidate_id": candidate.id,
            "publication_id": selection.publication.id,
            "publication_title": selection.publication.title,
            "rank": selection.rank,
            "selection_score": selection.score,
            "overall_outreach_score": selection.authorship.score,
            "rejection_reasons": reasons,
            "pdf_eligibility_type": selection.pdf_eligibility.source_type,
            "pdf_eligible": selection.pdf_eligibility.eligible,
        },
    )


def log_workflow_transition(
    workflow: ResearchWorkflowRun,
    *,
    from_stage: str,
    to_stage: str,
    publication: Publication | None = None,
    selection: RankedPublicationSelection | None = None,
    exception: Exception | None = None,
    reason: str | None = None,
) -> None:
    eligibility = selection.pdf_eligibility if selection else None
    logger.info(
        "workflow_transition",
        extra={
            "workflow_run_id": workflow.id,
            "candidate_id": workflow.candidate_id,
            "publication_id": publication.id if publication else None,
            "publication_title": publication.title if publication else None,
            "ranking_position": selection.rank if selection else None,
            "total_score": selection.score if selection else None,
            "portfolio_similarity": (
                _score_components(selection.authorship).get("portfolio_similarity")
                if selection
                else None
            ),
            "pdf_eligibility_type": eligibility.source_type if eligibility else None,
            "canonical_pdf_url_host": (
                url_host(eligibility.canonical_pdf_url) if eligibility else None
            ),
            "state_from": from_stage,
            "state_to": to_stage,
            "exception_type": exception.__class__.__name__ if exception else None,
            "failure_reason": reason,
        },
    )


def url_host(url: str | None) -> str | None:
    if not url:
        return None
    return urlparse(url).hostname


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
    workflow: ResearchWorkflowRun,
    commit_checkpoints: bool = False,
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
    if selected_provider.name != "mock":
        assert_ai_request_allowed(workflow_id=workflow.id)
        record_ai_request(workflow_id=workflow.id)
        workflow.ai_request_count += 1
    commit_workflow_checkpoint(session, enabled=commit_checkpoints)
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
    profile = (
        session.get(ResearcherProfile, workflow.researcher_profile_id)
        if workflow.researcher_profile_id
        else latest_researcher_profile(session, workflow.candidate_id)
    )
    return {
        "workflow": workflow,
        "workflow_selection_reasons": _json_list(workflow.selection_reasons_json),
        "workflow_rejected_alternatives": _json_list(workflow.rejected_alternatives_json),
        "workflow_retrieval_result": _json_object(workflow.retrieval_result_json),
        "workflow_summary": _json_object(workflow.summary_json),
        "workflow_claim_checks": _json_list(workflow.claim_check_json),
        "researcher_profile": profile,
        "researcher_profile_view": profile_view(profile),
        "attachments_ready": required_attachments_ready(),
        "portfolio_input_status": load_research_portfolio_text_status(),
    }


def set_stage(workflow: ResearchWorkflowRun, stage: str) -> None:
    workflow.current_stage = stage


def commit_workflow_checkpoint(session: Session, *, enabled: bool) -> None:
    if enabled:
        session.commit()


def fail_workflow(workflow: ResearchWorkflowRun, stage: str, reason: str) -> None:
    workflow.status = "FAILED"
    workflow.failed_stage = stage
    workflow.failure_reason = reason
    workflow.current_stage = stage


def wait_for_portfolio_input(workflow: ResearchWorkflowRun, reason: str | None) -> None:
    workflow.status = "WAITING_FOR_PORTFOLIO_INPUT"
    workflow.failed_stage = None
    workflow.current_stage = "Loading portfolio input"
    workflow.failure_reason = (
        "PORTFOLIO_INPUT_UNAVAILABLE: "
        f"{reason or 'Research portfolio text is unavailable.'} "
        "Upload the private resume and research portfolio PDFs in Settings, then resume this "
        "workflow."
    )


def prepare_workflow_for_resume(workflow: ResearchWorkflowRun) -> None:
    workflow.status = "RUNNING"
    workflow.current_stage = "Finding publications"
    workflow.failed_stage = None
    workflow.failure_reason = None


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
