import json
import logging
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.candidate import Candidate, CandidateStatus
from app.models.discovery import DiscoveryCandidate, DiscoveryDecision, DiscoveryScreeningStatus
from app.models.draft import Draft
from app.models.email_address import EmailAddress
from app.models.outreach import OutreachEvent, OutreachEventType
from app.models.workflow import ResearchWorkflowRun
from app.services.ai_providers import (
    AIProvider,
    AIProviderError,
    DraftReviewOutput,
    DraftReviewRequest,
    get_ai_provider,
)
from app.services.ai_usage import (
    AIRequestLimitError,
    assert_ai_request_allowed,
    record_ai_request,
)
from app.services.candidates import detect_duplicate_warnings
from app.services.discovery import save_discovery_candidate
from app.services.drafting import contains_forbidden_phrase, primary_verified_email
from app.services.metadata import (
    candidate_has_publications_for_openalex_author,
    list_candidate_publication_reviews,
    list_openalex_author_candidates_for_candidate,
    retrieve_recent_publications_for_candidate,
)
from app.services.research_workflow import (
    latest_workflow_run,
    run_research_workflow,
)
from app.services.review import manual_review_context

logger = logging.getLogger("professor_outreach.outreach_agent")
CONTACTED_STATUSES = {
    CandidateStatus.OUTLOOK_DRAFT_CREATED,
    CandidateStatus.SENT,
    CandidateStatus.REPLIED,
    CandidateStatus.DECLINED,
    CandidateStatus.FOLLOW_UP_DUE,
    CandidateStatus.CLOSED,
}
MIN_AUTO_OPENALEX_CONFIDENCE = 0.80
MIN_AUTO_OPENALEX_MARGIN = 0.05
MAX_AGENT_CANDIDATES = 8


@dataclass(frozen=True)
class OutreachCandidateOption:
    candidate: Candidate
    score: float
    source: str
    reasons: list[str]


@dataclass(frozen=True)
class OutreachAgentResult:
    success: bool
    draft: Draft | None
    candidate: Candidate | None
    attempts: list[dict[str, object]]
    message: str


def start_outreach(session: Session, *, provider: AIProvider | None = None) -> OutreachAgentResult:
    attempts: list[dict[str, object]] = []
    options = outreach_candidate_options(session)
    if not options:
        return OutreachAgentResult(
            success=False,
            draft=None,
            candidate=None,
            attempts=[],
            message=(
                "No uncontacted outreach candidates are available yet. Add candidates or approved "
                "discovery previews, then press Start Outreach again."
            ),
        )

    selected_provider = provider or get_ai_provider()
    for option in options[:MAX_AGENT_CANDIDATES]:
        candidate = option.candidate
        attempt: dict[str, object] = {
            "candidate_id": candidate.id,
            "candidate_name": candidate.full_name,
            "selection_score": round(option.score, 2),
            "source": option.source,
            "selection_reasons": option.reasons,
        }
        attempts.append(attempt)
        if already_contacted(session, candidate):
            attempt["status"] = "skipped"
            attempt["reason"] = "Candidate was already contacted."
            continue
        try:
            author_resolution = ensure_high_confidence_openalex_author(session, candidate)
            attempt["openalex_author"] = author_resolution
            existing_workflow = latest_workflow_run(session, candidate.id)
            workflow = run_research_workflow(
                session,
                candidate=candidate,
                provider=selected_provider,
                workflow=workflow_for_agent_resume(existing_workflow),
            )
            attempt["workflow_id"] = workflow.id
            attempt["workflow_status"] = workflow.status
            attempt["workflow_stage"] = workflow.current_stage
            if workflow.status != "READY_FOR_REVIEW" or workflow.draft_id is None:
                attempt["status"] = "skipped"
                attempt["reason"] = workflow.failure_reason or workflow.status
                continue
            draft = session.get(Draft, workflow.draft_id)
            if draft is None:
                attempt["status"] = "skipped"
                attempt["reason"] = "Workflow did not save a draft."
                continue
            ai_review = run_second_ai_review(
                session,
                candidate=candidate,
                draft=draft,
                provider=selected_provider,
                workflow_id=workflow.id,
            )
            attempt["ai_review"] = ai_review.model_dump()
            if not ai_review.overall_passed:
                attempt["status"] = "skipped"
                attempt["reason"] = "Second AI review did not pass the draft."
                continue
            draft.ai_review_json = ai_review.model_dump_json()
            attempt["status"] = "success"
            logger.info(
                "outreach_agent_success",
                extra={
                    "candidate_id": candidate.id,
                    "draft_id": draft.id,
                    "workflow_id": workflow.id,
                },
            )
            return OutreachAgentResult(
                success=True,
                draft=draft,
                candidate=candidate,
                attempts=attempts,
                message="Finished a copy-ready outreach draft.",
            )
        except (AIProviderError, AIRequestLimitError, ValueError) as exc:
            attempt["status"] = "skipped"
            attempt["reason"] = str(exc)
            logger.info(
                "outreach_agent_candidate_skipped",
                extra={"candidate_id": candidate.id, "reason": str(exc)},
            )
            continue

    return OutreachAgentResult(
        success=False,
        draft=None,
        candidate=None,
        attempts=attempts,
        message="The agent tried the available candidates but could not finish a safe draft.",
    )


def workflow_for_agent_resume(workflow: ResearchWorkflowRun | None) -> ResearchWorkflowRun | None:
    if workflow is None:
        return None
    status = getattr(workflow, "status", None)
    if status == "FAILED":
        return None
    return workflow


def outreach_candidate_options(session: Session) -> list[OutreachCandidateOption]:
    options = [*saved_candidate_options(session), *discovered_candidate_options(session)]
    return sorted(options, key=lambda item: item.score, reverse=True)


def saved_candidate_options(session: Session) -> list[OutreachCandidateOption]:
    candidates = session.scalars(
        select(Candidate).where(Candidate.deleted_at.is_(None)),
    )
    options = [
        OutreachCandidateOption(
            candidate=candidate,
            score=score_saved_candidate(session, candidate),
            source="saved_candidate",
            reasons=candidate_selection_reasons(session, candidate),
        )
        for candidate in candidates
        if not already_contacted(session, candidate)
    ]
    return sorted(options, key=lambda item: item.score, reverse=True)


def discovered_candidate_options(session: Session) -> list[OutreachCandidateOption]:
    previews = session.scalars(
        select(DiscoveryCandidate).where(
            DiscoveryCandidate.decision == DiscoveryDecision.REVIEW_PENDING,
            DiscoveryCandidate.screening_status != DiscoveryScreeningStatus.EXCLUDED,
        ),
    )
    options: list[OutreachCandidateOption] = []
    for preview in previews:
        if detect_duplicate_warnings(
            session,
            full_name=preview.full_name,
            institution=preview.institution,
            email=preview.official_email,
        ):
            continue
        candidate = save_discovery_candidate(session, preview)
        if not already_contacted(session, candidate):
            options.append(
                OutreachCandidateOption(
                    candidate=candidate,
                    score=max(preview.screening_score, preview.score),
                    source="discovery_preview",
                    reasons=["Saved automatically from a screened discovery preview."],
                ),
            )
    session.flush()
    return sorted(options, key=lambda item: item.score, reverse=True)


def score_saved_candidate(session: Session, candidate: Candidate) -> float:
    score = 0.0
    if candidate.openalex_author_id:
        score += 35.0
    if primary_verified_email(session, candidate.id):
        score += 25.0
    if candidate.official_profile_url:
        score += 10.0
    if candidate.research_area:
        score += 10.0
    if list_candidate_publication_reviews(session, candidate.id):
        score += 20.0
    if candidate.title and "professor" in candidate.title.lower():
        score += 5.0
    return score


def candidate_selection_reasons(session: Session, candidate: Candidate) -> list[str]:
    reasons: list[str] = []
    if candidate.openalex_author_id:
        reasons.append("Confirmed OpenAlex author is already saved.")
    if primary_verified_email(session, candidate.id):
        reasons.append("Verified official email is saved.")
    if list_candidate_publication_reviews(session, candidate.id):
        reasons.append("Publication metadata is already available.")
    if candidate.research_area:
        reasons.append("Research area is recorded for matching.")
    return reasons or ["Candidate is uncontacted and available for outreach."]


def already_contacted(session: Session, candidate: Candidate) -> bool:
    if candidate.status in CONTACTED_STATUSES:
        return True
    contacted_event = session.scalars(
        select(OutreachEvent).where(
            OutreachEvent.candidate_id == candidate.id,
            OutreachEvent.event_type.in_(
                [
                    OutreachEventType.DRAFT_APPROVED,
                    OutreachEventType.MANUALLY_MARKED_SENT,
                    OutreachEventType.REPLY_RECORDED,
                    OutreachEventType.DECLINED,
                ],
            ),
        ),
    ).first()
    if contacted_event is not None:
        return True
    primary_email = primary_verified_email(session, candidate.id)
    if primary_email is None:
        return False
    duplicate_sent_email = session.scalars(
        select(EmailAddress)
        .join(Candidate, Candidate.id == EmailAddress.candidate_id)
        .where(
            func.lower(EmailAddress.email) == primary_email.email.lower(),
            Candidate.id != candidate.id,
            Candidate.status.in_(CONTACTED_STATUSES),
        ),
    ).first()
    return duplicate_sent_email is not None


def ensure_high_confidence_openalex_author(
    session: Session,
    candidate: Candidate,
) -> dict[str, object]:
    if candidate.openalex_author_id:
        if not candidate_has_publications_for_openalex_author(
            session,
            candidate_id=candidate.id,
            openalex_author_id=candidate.openalex_author_id,
        ):
            retrieve_recent_publications_for_candidate(session, candidate=candidate)
        return {
            "status": "already_confirmed",
            "openalex_id": candidate.openalex_author_id,
        }

    author_candidates = list_openalex_author_candidates_for_candidate(candidate)
    if not author_candidates:
        raise ValueError("OpenAlex did not return a plausible author profile.")
    chosen = author_candidates[0]
    runner_up = author_candidates[1] if len(author_candidates) > 1 else None
    margin = chosen.confidence - (runner_up.confidence if runner_up else 0.0)
    if chosen.confidence < MIN_AUTO_OPENALEX_CONFIDENCE or margin < MIN_AUTO_OPENALEX_MARGIN:
        raise ValueError(
            "OpenAlex author confidence is too low for automatic confirmation "
            f"({chosen.display_name}, confidence {chosen.confidence:.2f}, margin {margin:.2f})."
        )
    candidate.openalex_author_id = chosen.openalex_id
    retrieve_recent_publications_for_candidate(
        session,
        candidate=candidate,
        confirmed_openalex_author_id=chosen.openalex_id,
    )
    return {
        "status": "auto_confirmed",
        "openalex_id": chosen.openalex_id,
        "name": chosen.display_name,
        "confidence": chosen.confidence,
        "margin": margin,
        "reasons": chosen.reasons,
    }


def run_second_ai_review(
    session: Session,
    *,
    candidate: Candidate,
    draft: Draft,
    provider: AIProvider,
    workflow_id: int,
) -> DraftReviewOutput:
    if draft.ai_review_json and draft.ai_review_json != "{}":
        return DraftReviewOutput.model_validate(json.loads(draft.ai_review_json))
    if provider.name != "mock":
        assert_ai_request_allowed(workflow_id=workflow_id)
        record_ai_request(workflow_id=workflow_id)
    context = manual_review_context(session, draft=draft)
    if context.workflow is not None:
        context.workflow.ai_request_count += 1
    evidence_summary = "\n".join(
        f"- {item.claim} | page {item.page_number} | {item.evidence_text}"
        for item in context.evidence[:8]
    )
    publication_title = context.publication.title if context.publication else "Unknown paper"
    review = provider.review_draft(
        DraftReviewRequest(
            recipient_name=candidate.full_name,
            paper_title=publication_title,
            draft_subject=draft.subject,
            draft_body=draft.body_text,
            evidence_summary=evidence_summary,
            deterministic_checks=context.sentence_checks,
        ),
    )
    if contains_forbidden_phrase(draft.body_text):
        review = review.model_copy(
            update={
                "naturalness_check_passed": False,
                "overall_passed": False,
                "concerns": [
                    *review.concerns,
                    "Draft contains forbidden AI-sounding wording.",
                ],
            },
        )
    return review


def load_draft_ai_review(draft: Draft) -> DraftReviewOutput | None:
    if not draft.ai_review_json or draft.ai_review_json == "{}":
        return None
    return DraftReviewOutput.model_validate(json.loads(draft.ai_review_json))
