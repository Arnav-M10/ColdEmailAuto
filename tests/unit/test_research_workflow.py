from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from pypdf import PdfWriter
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import create_engine_for_url, initialize_database
from app.models.candidate import Candidate
from app.models.draft import Draft
from app.models.paper import EvidenceClassification, EvidenceItem, PaperAnalysis, PaperFile
from app.models.publication import Authorship, Publication
from app.models.workflow import ResearchWorkflowRun
from app.services.ai_providers import EvidenceClaim, MockProvider, PaperAnalysisOutput
from app.services.candidates import add_email_address, create_candidate
from app.services.metadata import title_fingerprint
from app.services.research_workflow import run_research_workflow, select_best_publication
from app.services.web_safety import FetchResult


def session_for(tmp_path: Path) -> Session:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'workflow.db'}")
    initialize_database(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def candidate(session: Session) -> Candidate:
    candidate_record = create_candidate(
        session,
        full_name="Professor Jane Doe",
        title="Assistant Professor",
        institution="Example University",
        department="Physics",
        research_area="computational astrophysics magnetic fields",
        official_profile_url="https://example.edu/jane",
        notes=None,
    )
    add_email_address(
        session,
        candidate_id=candidate_record.id,
        email="jane@example.edu",
        source_url="https://example.edu/jane",
        source_type="official_faculty_profile",
        confidence="HIGH",
        verification_status="VERIFIED",
    )
    return candidate_record


def publication(
    session: Session,
    candidate_record: Candidate,
    *,
    title: str,
    score: float,
    arxiv_id: str | None = None,
    year: int = 2025,
    author_count: int = 2,
) -> Publication:
    record = Publication(
        title=title,
        title_fingerprint=title_fingerprint(title),
        year=year,
        venue="Example Journal",
        doi=f"10.1000/{title_fingerprint(title)}",
        arxiv_id=arxiv_id,
        openalex_id=f"https://openalex.org/W{abs(hash(title))}",
        source="openalex",
        open_access_url=f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else None,
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else None,
        author_count=author_count,
        citation_count=15,
        work_type="article",
        metadata_json="{}",
    )
    session.add(record)
    session.flush()
    session.add(
        Authorship(
            candidate_id=candidate_record.id,
            publication_id=record.id,
            author_position=1,
            author_count=author_count,
            openalex_author_id="https://openalex.org/A1",
            confirmed_author_present=True,
            corresponding_author=False,
            role="first_author",
            identity_confidence=0.95,
            match_status="MATCHED",
            score=score,
            connection_summary="magnetic fields, computational astrophysics",
            warnings_json="[]",
            score_details_json=(
                '{"components":{"portfolio_similarity":30.0},'
                '"reasons":["Portfolio similarity matched: magnetic, astrophysics.",'
                '"Confirmed author is first author.","Author count: 2.",'
                '"Recent publication from 2025.",'
                '"Lawful full text or open-access page is available."]}'
            ),
        ),
    )
    session.flush()
    return record


def pdf_bytes(seed: str) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_metadata({"/Title": seed})
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class FakePDFFetcher:
    def __init__(self, seed: str = "workflow") -> None:
        self.seed = seed
        self.urls: list[str] = []

    def fetch(self, url: str, *, expected: str = "pdf") -> FetchResult:
        self.urls.append(url)
        return FetchResult(
            url=url,
            final_url=url,
            status_code=200,
            content_type="application/pdf",
            body=pdf_bytes(self.seed),
            sha256="f" * 64,
            robots_allowed=True,
        )


class FailingThenSuccessfulPDFFetcher:
    def __init__(self, successful_url: str, seed: str = "fallback") -> None:
        self.successful_url = successful_url
        self.seed = seed
        self.urls: list[str] = []

    def fetch(self, url: str, *, expected: str = "pdf") -> FetchResult:
        self.urls.append(url)
        if url != self.successful_url:
            return FetchResult(
                url=url,
                final_url=url,
                status_code=200,
                content_type="text/html",
                body=b"<html>not a pdf</html>",
                sha256="0" * 64,
                robots_allowed=True,
            )
        return FetchResult(
            url=url,
            final_url=url,
            status_code=200,
            content_type="application/pdf",
            body=pdf_bytes(self.seed),
            sha256="1" * 64,
            robots_allowed=True,
        )


class AlwaysFailingPDFFetcher:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def fetch(self, url: str, *, expected: str = "pdf") -> FetchResult:
        self.urls.append(url)
        return FetchResult(
            url=url,
            final_url=url,
            status_code=200,
            content_type="text/html",
            body=b"<html>not a pdf</html>",
            sha256="2" * 64,
            robots_allowed=True,
        )


class ExplodingPDFFetcher:
    def fetch(self, url: str, *, expected: str = "pdf") -> FetchResult:
        raise RuntimeError("network client exploded")


def mock_provider() -> MockProvider:
    return MockProvider(
        PaperAnalysisOutput(
            title="Magnetic Structures in Time-Domain Surveys",
            research_question="How can time-domain surveys identify magnetic structures?",
            motivation="The paper studies time-domain astrophysics.",
            methods="The paper uses numerical checks and survey analysis.",
            results="The paper reports a compact analysis workflow for survey signals.",
            overclaim_risks="Do not imply the result was reproduced locally.",
            connection_to_arnav="scientific Python, magnetic-field analysis, and numerical checks",
            confidence=0.84,
            evidence=[
                EvidenceClaim(
                    claim="the paper uses numerical checks for survey signals",
                    evidence_text="The paper uses numerical checks and survey analysis.",
                    page_number=1,
                    section_name="Extracted text",
                    classification=EvidenceClassification.EXPLICIT,
                    confidence=0.9,
                ),
            ],
        ),
    )


def make_portfolio_available(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "app.services.research_workflow.load_research_portfolio_text_status",
        lambda: SimpleNamespace(
            available=True,
            text="magnetic fields computational astrophysics survey analysis",
            status="AVAILABLE",
            reason=None,
        ),
    )


def test_auto_selection_skips_high_score_without_lawful_full_text(tmp_path: Path) -> None:
    with session_for(tmp_path) as session:
        candidate_record = candidate(session)
        metadata_only = publication(
            session,
            candidate_record,
            title="Magnetic Fields Without Public PDF",
            score=92.0,
            arxiv_id=None,
        )
        retrievable = publication(
            session,
            candidate_record,
            title="Magnetic Fields With Public PDF",
            score=88.0,
            arxiv_id="2501.12345",
        )

        selected = select_best_publication(session, candidate=candidate_record)

        assert selected.publication == retrievable
        assert selected.metadata_only == metadata_only
        assert selected.rejected[0]["title"] == "Magnetic Fields Without Public PDF"
        rejected_reasons = cast(list[str], selected.rejected[0]["reasons"])
        assert "DOI-only metadata is not a lawful PDF source" in " ".join(rejected_reasons)


def test_research_workflow_persists_selected_paper_analysis_and_draft(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    make_portfolio_available(monkeypatch)
    monkeypatch.setattr(
        "app.services.research_workflow.required_attachments_ready",
        lambda: True,
    )
    with session_for(tmp_path) as session:
        candidate_record = candidate(session)
        candidate_record.openalex_author_id = "https://openalex.org/A1"
        selected_publication = publication(
            session,
            candidate_record,
            title="Magnetic Structures in Time-Domain Surveys",
            score=91.0,
            arxiv_id="2502.54321",
        )
        fetcher = FakePDFFetcher("workflow-success")

        workflow = run_research_workflow(
            session,
            candidate=candidate_record,
            provider=mock_provider(),
            pdf_fetcher=fetcher,
        )
        session.commit()

        assert workflow.status == "READY_FOR_REVIEW"
        assert workflow.selected_publication_id == selected_publication.id
        assert workflow.paper_file_id is not None
        assert workflow.analysis_id is not None
        assert workflow.draft_id is not None
        assert fetcher.urls == ["https://arxiv.org/pdf/2502.54321"]
        assert session.get(ResearchWorkflowRun, workflow.id) is not None
        assert session.get(PaperFile, workflow.paper_file_id) is not None
        assert session.get(PaperAnalysis, workflow.analysis_id) is not None
        assert session.get(Draft, workflow.draft_id) is not None
        assert session.query(EvidenceItem).count() == 1


def test_research_workflow_blocks_ready_state_when_attachments_are_missing(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    make_portfolio_available(monkeypatch)
    monkeypatch.setattr(
        "app.services.research_workflow.required_attachments_ready",
        lambda: False,
    )
    with session_for(tmp_path) as session:
        candidate_record = candidate(session)
        candidate_record.openalex_author_id = "https://openalex.org/A1"
        publication(
            session,
            candidate_record,
            title="Magnetic Structures in Missing Asset Workflow",
            score=90.0,
            arxiv_id="2503.11111",
        )

        workflow = run_research_workflow(
            session,
            candidate=candidate_record,
            provider=mock_provider(),
            pdf_fetcher=FakePDFFetcher("missing-assets"),
        )

    assert workflow.status == "FAILED"
    assert workflow.failed_stage == "Verifying attachments"
    assert "resume and research portfolio PDFs" in (workflow.failure_reason or "")
    assert workflow.draft_id is None


def test_workflow_attempts_direct_pdf_before_manual_selection(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    make_portfolio_available(monkeypatch)
    monkeypatch.setattr("app.services.research_workflow.required_attachments_ready", lambda: True)
    with session_for(tmp_path) as session:
        candidate_record = candidate(session)
        candidate_record.openalex_author_id = "https://openalex.org/A1"
        selected = publication(
            session,
            candidate_record,
            title="Direct PDF Outreach Match",
            score=94.0,
            arxiv_id=None,
        )
        selected.pdf_url = "https://iopscience.iop.org/article/10.1088/example/pdf"
        fetcher = FakePDFFetcher("direct-pdf")

        workflow = run_research_workflow(
            session,
            candidate=candidate_record,
            provider=mock_provider(),
            pdf_fetcher=fetcher,
        )

    assert workflow.status == "READY_FOR_REVIEW"
    assert workflow.selected_publication_id == selected.id
    assert fetcher.urls == ["https://iopscience.iop.org/article/10.1088/example/pdf"]


def test_workflow_falls_back_when_top_pdf_retrieval_fails(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    make_portfolio_available(monkeypatch)
    monkeypatch.setattr("app.services.research_workflow.required_attachments_ready", lambda: True)
    with session_for(tmp_path) as session:
        candidate_record = candidate(session)
        candidate_record.openalex_author_id = "https://openalex.org/A1"
        publication(
            session,
            candidate_record,
            title="Top Ranked Broken PDF",
            score=96.0,
            arxiv_id="2501.11111",
        )
        fallback = publication(
            session,
            candidate_record,
            title="Second Ranked Working PDF",
            score=92.0,
            arxiv_id="2501.22222",
        )
        fetcher = FailingThenSuccessfulPDFFetcher("https://arxiv.org/pdf/2501.22222")

        workflow = run_research_workflow(
            session,
            candidate=candidate_record,
            provider=mock_provider(),
            pdf_fetcher=fetcher,
        )
        result = workflow.retrieval_result_json

    assert workflow.status == "READY_FOR_REVIEW"
    assert workflow.selected_publication_id == fallback.id
    assert fetcher.urls == [
        "https://arxiv.org/pdf/2501.11111",
        "https://arxiv.org/pdf/2501.22222",
    ]
    assert "Top Ranked Broken PDF" in result
    assert "Second Ranked Working PDF" in result


def test_workflow_waits_for_manual_selection_when_top_score_tie(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    make_portfolio_available(monkeypatch)
    with session_for(tmp_path) as session:
        candidate_record = candidate(session)
        candidate_record.openalex_author_id = "https://openalex.org/A1"
        publication(
            session,
            candidate_record,
            title="Tied Eligible PDF One",
            score=94.0,
            arxiv_id="2501.12121",
        )
        publication(
            session,
            candidate_record,
            title="Tied Eligible PDF Two",
            score=94.0,
            arxiv_id="2501.34343",
        )
        fetcher = FakePDFFetcher("tie")

        workflow = run_research_workflow(
            session,
            candidate=candidate_record,
            provider=mock_provider(),
            pdf_fetcher=fetcher,
        )

    assert workflow.status == "WAITING_FOR_MANUAL_PAPER_SELECTION"
    assert workflow.current_stage == "Resolving tied publications"
    assert workflow.selected_publication_id is None
    assert "tied for the highest automatic outreach score" in (workflow.failure_reason or "")
    assert "automatic_selection_tie" in workflow.retrieval_result_json
    assert fetcher.urls == []


def test_workflow_enters_manual_only_after_all_suitable_pdfs_fail(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    make_portfolio_available(monkeypatch)
    with session_for(tmp_path) as session:
        candidate_record = candidate(session)
        candidate_record.openalex_author_id = "https://openalex.org/A1"
        publication(
            session,
            candidate_record,
            title="Broken Suitable PDF One",
            score=96.0,
            arxiv_id="2501.33333",
        )
        publication(
            session,
            candidate_record,
            title="Broken Suitable PDF Two",
            score=92.0,
            arxiv_id="2501.44444",
        )
        fetcher = AlwaysFailingPDFFetcher()

        workflow = run_research_workflow(
            session,
            candidate=candidate_record,
            provider=mock_provider(),
            pdf_fetcher=fetcher,
        )

    assert workflow.status == "WAITING_FOR_MANUAL_PAPER_SELECTION"
    assert workflow.selected_publication_id is None
    assert "All automatically suitable publications failed" in (workflow.failure_reason or "")
    assert fetcher.urls == [
        "https://arxiv.org/pdf/2501.33333",
        "https://arxiv.org/pdf/2501.44444",
    ]
    assert "all_suitable_papers_exhausted" in workflow.retrieval_result_json


def test_broad_retrieval_exception_fails_workflow_not_manual_selection(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    make_portfolio_available(monkeypatch)
    with session_for(tmp_path) as session:
        candidate_record = candidate(session)
        candidate_record.openalex_author_id = "https://openalex.org/A1"
        publication(
            session,
            candidate_record,
            title="Exploding Retrieval PDF",
            score=95.0,
            arxiv_id="2501.55555",
        )

        workflow = run_research_workflow(
            session,
            candidate=candidate_record,
            provider=mock_provider(),
            pdf_fetcher=ExplodingPDFFetcher(),
        )

    assert workflow.status == "FAILED"
    assert workflow.failed_stage == "Retrieving PDF"
    assert "RuntimeError" in (workflow.failure_reason or "")
    assert workflow.selected_publication_id is not None
