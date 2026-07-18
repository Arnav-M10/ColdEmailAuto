from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.draft import Draft
from app.models.paper import EvidenceItem, PaperAnalysis, PaperFile
from app.models.publication import Authorship, Publication
from app.models.workflow import ResearchWorkflowRun
from app.services.assets import AssetStatus, build_asset_manifest
from app.services.drafting import (
    primary_verified_email,
    sentence_claim_checks,
    validate_draft_approval,
)


@dataclass(frozen=True)
class ManualReviewContext:
    draft: Draft
    workflow: ResearchWorkflowRun | None
    analysis: PaperAnalysis | None
    paper_file: PaperFile | None
    publication: Publication | None
    authorship: Authorship | None
    evidence: list[EvidenceItem]
    recipient_email: str | None
    recipient_source_url: str | None
    attachment_statuses: list[AssetStatus]
    approval_errors: list[str]
    sentence_checks: list[dict[str, str]]
    summary: dict[str, object]

    @property
    def ready(self) -> bool:
        return not self.approval_errors


def manual_review_context(session: Session, *, draft: Draft) -> ManualReviewContext:
    workflow = session.scalars(
        select(ResearchWorkflowRun)
        .where(ResearchWorkflowRun.draft_id == draft.id)
        .order_by(ResearchWorkflowRun.created_at.desc()),
    ).first()
    analysis = (
        session.get(PaperAnalysis, workflow.analysis_id)
        if workflow and workflow.analysis_id
        else None
    )
    paper_file = (
        session.get(PaperFile, workflow.paper_file_id)
        if workflow and workflow.paper_file_id
        else None
    )
    publication = (
        session.get(Publication, workflow.selected_publication_id)
        if workflow and workflow.selected_publication_id
        else None
    )
    authorship = (
        session.scalars(
            select(Authorship).where(
                Authorship.candidate_id == draft.candidate_id,
                Authorship.publication_id == publication.id,
            ),
        ).first()
        if publication is not None
        else None
    )
    evidence = (
        list(
            session.scalars(
                select(EvidenceItem)
                .where(EvidenceItem.analysis_id == analysis.id)
                .order_by(EvidenceItem.page_number.asc()),
            ),
        )
        if analysis is not None
        else []
    )
    primary_email = primary_verified_email(session, draft.candidate_id)
    return ManualReviewContext(
        draft=draft,
        workflow=workflow,
        analysis=analysis,
        paper_file=paper_file,
        publication=publication,
        authorship=authorship,
        evidence=evidence,
        recipient_email=primary_email.email if primary_email else None,
        recipient_source_url=primary_email.source_url if primary_email else None,
        attachment_statuses=build_asset_manifest().assets,
        approval_errors=validate_draft_approval(session, draft=draft),
        sentence_checks=sentence_claim_checks(session, draft=draft),
        summary=summary_for_review(analysis=analysis, evidence=evidence),
    )


def summary_for_review(
    *,
    analysis: PaperAnalysis | None,
    evidence: list[EvidenceItem],
) -> dict[str, object]:
    if analysis is None:
        return {}
    explicit = [item for item in evidence if str(item.classification).endswith("EXPLICIT")]
    first = explicit[0] if explicit else evidence[0] if evidence else None
    return {
        "what_the_paper_is_about": analysis.research_question,
        "what_the_researcher_did": analysis.methods,
        "what_they_found": analysis.results,
        "why_it_matters": analysis.results,
        "connection_to_arnav": analysis.connection_to_arnav,
        "realistic_help": "coding, numerical checks, data analysis, or visualization",
        "avoid_claiming": analysis.overclaim_risks or "Do not claim independent verification.",
        "best_supported_detail": first.claim if first else None,
    }
