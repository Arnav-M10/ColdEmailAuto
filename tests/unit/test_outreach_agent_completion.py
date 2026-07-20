from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.session import create_engine_for_url, initialize_database
from app.models.candidate import Candidate
from app.models.draft import Draft
from app.models.paper import PaperFile
from app.models.publication import Authorship, Publication
from app.models.workflow import ResearchWorkflowRun
from app.services.ai_providers import (
    DraftReviewOutput,
    DraftReviewRequest,
    EvidenceClaim,
    EvidenceClassification,
    MockProvider,
    PaperAnalysisOutput,
    PaperAnalysisRequest,
)
from app.services.ai_usage import record_ai_request
from app.services.candidates import add_email_address, create_candidate
from app.services.metadata import title_fingerprint
from app.services.outreach_agent import start_outreach


def session_for(tmp_path: Path) -> Session:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'outreach.db'}")
    initialize_database(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def candidate_with_publication(session: Session) -> Candidate:
    candidate = create_candidate(
        session,
        full_name="Professor Jane Doe",
        title="Assistant Professor",
        institution="Example University",
        department="Physics",
        research_area="magnetic fields computational astrophysics",
        official_profile_url="https://example.edu/jane",
        notes=None,
    )
    candidate.openalex_author_id = "https://openalex.org/A1"
    publication = Publication(
        title="Magnetic Structures in Time-Domain Surveys",
        title_fingerprint=title_fingerprint("Magnetic Structures in Time-Domain Surveys"),
        year=2025,
        venue="Example Journal",
        doi="10.1000/outreach-unit",
        arxiv_id="2504.33333",
        openalex_id="https://openalex.org/WUNIT",
        source="openalex",
        open_access_url="https://arxiv.org/abs/2504.33333",
        pdf_url="https://arxiv.org/pdf/2504.33333",
        author_count=2,
        citation_count=9,
        work_type="article",
        metadata_json="{}",
    )
    session.add(publication)
    session.flush()
    session.add(
        Authorship(
            candidate_id=candidate.id,
            publication_id=publication.id,
            author_position=1,
            author_count=2,
            openalex_author_id="https://openalex.org/A1",
            confirmed_author_present=True,
            corresponding_author=False,
            role="first_author",
            identity_confidence=0.95,
            match_status="MATCHED",
            score=90.0,
            connection_summary="magnetic fields",
            warnings_json="[]",
            score_details_json=(
                '{"components":{"portfolio_similarity":30.0},'
                '"reasons":["Portfolio similarity matched: magnetic fields.",'
                '"Confirmed author is first author.","Author count: 2.",'
                '"Recent publication from 2025."]}'
            ),
        ),
    )
    add_email_address(
        session,
        candidate_id=candidate.id,
        email="jane@example.edu",
        source_url="https://example.edu/jane",
        source_type="official_faculty_profile",
        confidence="HIGH",
        verification_status="VERIFIED",
    )
    session.flush()
    return candidate


def analysis_output() -> PaperAnalysisOutput:
    return PaperAnalysisOutput(
        title="Magnetic Structures in Time-Domain Surveys",
        research_question="How do surveys identify magnetic structures?",
        motivation="The paper studies time-domain survey signals.",
        methods="The paper uses numerical checks and survey analysis.",
        results="The paper reports a compact analysis workflow.",
        overclaim_risks="Do not imply independent verification.",
        connection_to_arnav="scientific Python and magnetic-field analysis",
        confidence=0.84,
        evidence=[
            EvidenceClaim(
                claim="the paper uses numerical checks and survey analysis",
                evidence_text="The paper uses numerical checks and survey analysis.",
                page_number=1,
                section_name="Extracted text",
                classification=EvidenceClassification.EXPLICIT,
                confidence=0.9,
            ),
        ],
    )


def provider() -> MockProvider:
    return MockProvider(analysis_output())


class SuccessfulBudgetedProvider:
    name = "gemini"
    model = "unit-success"

    def __init__(self) -> None:
        self.calls = 0
        self.review_calls = 0

    def analyze_paper(self, request: PaperAnalysisRequest) -> PaperAnalysisOutput:
        del request
        self.calls += 1
        return analysis_output()

    def review_draft(self, request: DraftReviewRequest) -> DraftReviewOutput:
        del request
        self.review_calls += 1
        return DraftReviewOutput(
            hallucination_check_passed=True,
            accuracy_check_passed=True,
            naturalness_check_passed=True,
            concise=True,
            overall_passed=True,
            summary="The draft is grounded, concise, and natural.",
            concerns=[],
            suggested_edits=[],
            confidence=0.9,
        )


def test_start_outreach_completes_one_valid_candidate(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    text_path = create_parsed_paper_text(tmp_path)
    patch_workflow_dependencies(monkeypatch, tmp_path, text_path)

    selected_provider = provider()
    with session_for(tmp_path) as session:
        candidate_with_publication(session)

        result = start_outreach(session, provider=selected_provider)
        session.commit()

        assert result.success is True
        assert result.draft is not None
        assert selected_provider.calls == 1
        assert selected_provider.review_calls == 1
        workflow = session.query(ResearchWorkflowRun).one()
        draft = session.get(Draft, result.draft.id)
        assert workflow.status == "READY_FOR_REVIEW"
        assert workflow.analysis_id is not None
        assert workflow.paper_file_id is not None
        assert workflow.draft_id == result.draft.id
        assert draft is not None
        assert '"overall_passed":true' in draft.ai_review_json.replace(" ", "")


def test_start_outreach_uses_fresh_workflow_after_exhausted_failed_run(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    text_path = create_parsed_paper_text(tmp_path)
    patch_workflow_dependencies(monkeypatch, tmp_path, text_path)
    settings = Settings(
        runtime_data_dir=tmp_path / "data",
        private_asset_dir=tmp_path / "private_assets",
        ai_max_requests_per_workflow=2,
        ai_daily_request_limit=10,
    )
    monkeypatch.setattr("app.services.ai_usage.get_settings", lambda: settings)

    selected_provider = SuccessfulBudgetedProvider()
    with session_for(tmp_path) as session:
        candidate = candidate_with_publication(session)
        failed_workflow = ResearchWorkflowRun(
            candidate_id=candidate.id,
            status="FAILED",
            current_stage="Analyzing paper",
            failed_stage="Analyzing paper",
            failure_reason="Gemini returned HTTP 400.",
            ai_request_count=2,
        )
        session.add(failed_workflow)
        session.flush()
        record_ai_request(workflow_id=failed_workflow.id)
        record_ai_request(workflow_id=failed_workflow.id)

        result = start_outreach(session, provider=selected_provider)
        session.commit()

        workflows = session.query(ResearchWorkflowRun).order_by(ResearchWorkflowRun.id).all()
        assert result.success is True
        assert result.draft is not None
        assert selected_provider.calls == 1
        assert selected_provider.review_calls == 1
        assert len(workflows) == 2
        assert workflows[0].status == "FAILED"
        assert workflows[1].status == "READY_FOR_REVIEW"
        assert workflows[1].id != failed_workflow.id


def create_parsed_paper_text(tmp_path: Path) -> Path:
    text_dir = tmp_path / "data" / "cache" / "paper_text"
    text_dir.mkdir(parents=True, exist_ok=True)
    text_path = text_dir / "paper.txt"
    text_path.write_text(
        "--- Page 1 --- The paper uses numerical checks and survey analysis.",
        encoding="utf-8",
    )
    return text_path


def patch_workflow_dependencies(
    monkeypatch: Any,
    tmp_path: Path,
    text_path: Path,
) -> None:
    def fake_retrieve_publication_pdf(*args: Any, **kwargs: Any) -> PaperFile:
        session = args[0]
        candidate = kwargs["candidate"]
        publication = kwargs["publication"]
        paper = PaperFile(
            candidate_id=candidate.id,
            publication_id=publication.id,
            original_filename="paper.pdf",
            stored_path="papers/test/paper.pdf",
            sha256="3" * 64,
            size_bytes=512,
            page_count=1,
            parsed_text_path=str(text_path.relative_to(tmp_path)),
            source_url="https://arxiv.org/pdf/2504.33333",
            license_note="arXiv public PDF.",
            text_quality_json="{}",
        )
        session.add(paper)
        session.flush()
        return paper

    monkeypatch.setattr(
        "app.services.research_workflow.retrieve_publication_pdf",
        fake_retrieve_publication_pdf,
    )
    monkeypatch.setattr(
        "app.services.research_workflow.load_research_portfolio_text_status",
        lambda: SimpleNamespace(
            available=True,
            text="magnetic fields computational astrophysics survey analysis",
            status="AVAILABLE",
            reason=None,
        ),
    )
    monkeypatch.setattr("app.services.research_workflow.required_attachments_ready", lambda: True)
    monkeypatch.setattr("app.services.drafting.required_attachments_ready", lambda *_: True)
    monkeypatch.setattr(
        "app.services.papers.get_settings",
        lambda: SimpleNamespace(
            max_pdf_size_mb=25,
            project_root=tmp_path,
            resolved_runtime_data_dir=tmp_path / "data",
        ),
    )
