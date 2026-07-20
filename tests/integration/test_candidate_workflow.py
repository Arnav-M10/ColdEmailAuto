from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.session import create_engine_for_url, get_db, initialize_database
from app.main import create_app
from app.models.candidate import Candidate
from app.models.paper import PaperAnalysis, PaperFile
from app.models.publication import Authorship, Publication
from app.models.workflow import ResearchWorkflowRun
from app.security.csrf import csrf_token
from app.services.ai_providers import (
    EvidenceClaim,
    EvidenceClassification,
    MockProvider,
    PaperAnalysisOutput,
)
from app.services.candidates import add_email_address, create_candidate
from app.services.metadata import OpenAlexAuthorCandidate, PublicationMetadata, title_fingerprint
from app.services.web_safety import FetchResult


def build_test_context(tmp_path: Path) -> tuple[TestClient, Any]:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'test.db'}")
    initialize_database(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), session_factory


def build_test_client(tmp_path: Path) -> TestClient:
    client, _session_factory = build_test_context(tmp_path)
    return client


def test_candidate_can_be_created_and_opened(tmp_path: Path) -> None:
    client = build_test_client(tmp_path)

    response = client.post(
        "/candidates",
        data={
            "csrf": csrf_token(),
            "full_name": "Professor Jane Doe",
            "title": "Assistant Professor",
            "institution": "Example University",
            "department": "Physics",
            "research_area": "Computational astrophysics",
            "official_profile_url": "https://example.edu/jane-doe",
            "notes": "Manual test candidate",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Professor Jane Doe" in response.text

    detail = client.get("/candidates/1")
    assert detail.status_code == 200
    assert "Computational astrophysics" in detail.text


def test_candidate_email_can_be_recorded_with_source(tmp_path: Path) -> None:
    client = build_test_client(tmp_path)
    client.post(
        "/candidates",
        data={"csrf": csrf_token(), "full_name": "Professor Jane Doe"},
    )

    response = client.post(
        "/candidates/1/emails",
        data={
            "csrf": csrf_token(),
            "email": "Jane.Doe@Example.edu",
            "source_url": "https://example.edu/jane-doe",
            "source_type": "official_university_page",
            "confidence": "HIGH",
            "verification_status": "VERIFIED",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "jane.doe@example.edu" in response.text
    assert "official_university_page" in response.text


def test_contact_history_csv_preview_validates_rows(tmp_path: Path) -> None:
    client = build_test_client(tmp_path)

    response = client.post(
        "/contact-history/preview",
        data={"csrf": csrf_token()},
        files={
            "file": (
                "contacts.csv",
                b"name,email,institution,status\nAda,a@example.edu,Ex,SENT\n",
            ),
        },
    )

    assert response.status_code == 200
    assert "Ada" in response.text
    assert "Valid" in response.text


def test_contact_history_csv_import_creates_candidate(tmp_path: Path) -> None:
    client = build_test_client(tmp_path)

    response = client.post(
        "/contact-history/import",
        data={"csrf": csrf_token()},
        files={
            "file": (
                "contacts.csv",
                b"name,email,institution,status\nAda,a@example.edu,Example,SENT\n",
            ),
        },
    )

    assert response.status_code == 200
    assert "1 imported, 0 skipped" in response.text

    candidates = client.get("/candidates")
    assert "Ada" in candidates.text


def test_candidate_pdf_upload_creates_reviewable_paper(tmp_path: Path) -> None:
    client = build_test_client(tmp_path)
    client.post(
        "/candidates",
        data={"csrf": csrf_token(), "full_name": "Professor Jane Doe"},
    )
    source_pdf = tmp_path / "paper.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with source_pdf.open("wb") as file:
        writer.write(file)

    response = client.post(
        "/candidates/1/papers",
        data={"csrf": csrf_token()},
        files={"file": ("../../paper.pdf", source_pdf.read_bytes(), "application/pdf")},
        follow_redirects=True,
    )

    assert response.status_code == 200

    papers = client.get("/papers")
    assert "paper.pdf" in papers.text


def test_analysis_generates_reviewable_draft(tmp_path: Path) -> None:
    client = build_test_client(tmp_path)
    client.post(
        "/candidates",
        data={"csrf": csrf_token(), "full_name": "Professor Jane Doe"},
    )
    client.post(
        "/candidates/1/emails",
        data={
            "csrf": csrf_token(),
            "email": "jane@example.edu",
            "source_url": "https://example.edu/jane",
            "source_type": "official_university_page",
            "confidence": "HIGH",
            "verification_status": "VERIFIED",
        },
    )
    source_pdf = tmp_path / "paper.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with source_pdf.open("wb") as file:
        writer.write(file)
    client.post(
        "/candidates/1/papers",
        data={"csrf": csrf_token()},
        files={"file": ("paper.pdf", source_pdf.read_bytes(), "application/pdf")},
    )

    analysis_response = client.post(
        "/papers/1/analysis",
        data={
            "csrf": csrf_token(),
            "title": "magnetic field topology",
            "research_question": "How does field structure change?",
            "methods": "Persistent homology",
            "results": "The method identifies changes in structure.",
            "connection_to_arnav": "Parker Solar Probe magnetic-field analysis",
            "claim": "the use of persistent homology to track field structure",
            "evidence_text": "The paper uses persistent homology to compare field structure.",
            "page_number": "1",
            "section_name": "Methods",
            "classification": "EXPLICIT",
            "confidence": "0.9",
        },
        follow_redirects=True,
    )
    assert analysis_response.status_code == 200

    draft_response = client.post(
        "/analyses/1/draft",
        data={"csrf": csrf_token()},
        follow_redirects=True,
    )

    assert draft_response.status_code == 200
    assert "I enjoyed reading your paper" in draft_response.text
    assert "No automatic sending. No Mail.Send. No SMTP." in draft_response.text


def test_approved_draft_can_be_marked_sent_with_follow_up_suggestion(tmp_path: Path) -> None:
    client, session_factory = build_test_context(tmp_path)
    client.post(
        "/contact-history/import",
        data={"csrf": csrf_token()},
        files={
            "file": (
                "contacts.csv",
                b"name,email,institution,status\n"
                b"Professor Jane Doe,jane@example.edu,Example,DRAFT_READY\n",
            ),
        },
    )

    from app.models.draft import Draft

    with session_factory() as session:
        session.add(
            Draft(
                candidate_id=1,
                subject="Research inquiry",
                body_text="Approved local draft.",
                body_html=None,
                word_count=90,
                generation_version="test",
                approved_by_user=True,
            ),
        )
        session.commit()

    response = client.post(
        "/candidates/1/mark-sent",
        data={"csrf": csrf_token(), "sent_on": "2026-07-17"},
        follow_redirects=True,
    )
    follow_ups = client.get("/follow-ups")

    assert response.status_code == 200
    assert "Suggested follow-up" in response.text
    assert "2026-07-29" in follow_ups.text


def test_candidate_publication_memory_accepts_manual_scholar_source(tmp_path: Path) -> None:
    client = build_test_client(tmp_path)
    client.post(
        "/candidates",
        data={
            "csrf": csrf_token(),
            "full_name": "Professor Jane Doe",
            "research_area": "cosmology data analysis",
        },
    )

    response = client.post(
        "/candidates/1/publications/manual",
        data={
            "csrf": csrf_token(),
            "title": "Cosmology With Public Survey Data",
            "year": "2024",
            "venue": "Example Journal",
            "authors": "Professor Jane Doe, Other Person",
            "scholar_url": "https://scholar.google.com/citations?user=abc",
        },
        follow_redirects=True,
    )
    publications = client.get("/publications")

    assert response.status_code == 200
    assert "Cosmology With Public Survey Data" in response.text
    assert "Cosmology With Public Survey Data" in publications.text


def test_publication_pdf_retrieval_requires_paper_approval(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    client = build_test_client(tmp_path)
    client.post(
        "/candidates",
        data={
            "csrf": csrf_token(),
            "full_name": "Professor Jane Doe",
            "research_area": "cosmology data analysis",
        },
    )
    client.post(
        "/candidates/1/publications/manual",
        data={
            "csrf": csrf_token(),
            "title": "Cosmology With Public Survey Data",
            "year": "2024",
            "venue": "Example Journal",
            "authors": "Professor Jane Doe, Other Person",
            "arxiv_id": "2401.12345",
        },
    )

    selection = client.get("/candidates/1/publications/select")
    assert "Approve paper" in selection.text
    assert "Retrieve PDF" not in selection.text

    blocked = client.post(
        "/candidates/1/publications/1/retrieve",
        data={"csrf": csrf_token()},
        follow_redirects=False,
    )
    assert blocked.status_code == 400
    assert "Approve this paper" in blocked.text

    approved = client.post(
        "/candidates/1/publications/1/approve",
        data={"csrf": csrf_token(), "notes": "Good fit with local profile."},
        follow_redirects=True,
    )
    assert approved.status_code == 200
    assert "Selected for retrieval" in approved.text
    assert "Retrieve PDF" in approved.text

    called: list[int] = []

    def fake_retrieve_publication_pdf(*args: Any, **kwargs: Any) -> PaperFile:
        called.append(1)
        return PaperFile(
            id=42,
            candidate_id=1,
            publication_id=1,
            original_filename="paper.pdf",
            stored_path="papers/test/paper.pdf",
            sha256="9" * 64,
            size_bytes=128,
            page_count=1,
            parsed_text_path="data/cache/paper_text/test.txt",
            source_url="https://arxiv.org/pdf/2401.12345",
            license_note="arXiv public PDF.",
            text_quality_json="{}",
        )

    monkeypatch.setattr(
        "app.routes.publications.retrieve_publication_pdf",
        fake_retrieve_publication_pdf,
    )
    retrieved = client.post(
        "/candidates/1/publications/1/retrieve",
        data={"csrf": csrf_token()},
        follow_redirects=False,
    )

    assert retrieved.status_code == 303
    assert retrieved.headers["location"] == "/papers/42"
    assert called == [1]


def test_run_research_workflow_auto_selects_single_eligible_paper_without_selection_page(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    client, session_factory = build_test_context(tmp_path)
    with session_factory() as session:
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
            doi="10.1000/workflow-route",
            arxiv_id="2504.22222",
            openalex_id="https://openalex.org/WROUTE",
            source="openalex",
            open_access_url="https://arxiv.org/abs/2504.22222",
            pdf_url="https://arxiv.org/pdf/2504.22222",
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
                author_position=3,
                author_count=8,
                openalex_author_id="https://openalex.org/A1",
                confirmed_author_present=True,
                corresponding_author=False,
                role="middle_author",
                identity_confidence=0.95,
                match_status="MATCHED",
                score=90.0,
                connection_summary="magnetic fields",
                warnings_json="[]",
                score_details_json=(
                    '{"components":{"portfolio_similarity":30.0},'
                    '"reasons":["Portfolio similarity matched: magnetic fields.",'
                    '"Confirmed author appears at position 3.","Author count: 8.",'
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
        session.commit()

    settings = get_settings()
    text_dir = settings.project_root / "data" / "cache" / "paper_text"
    text_dir.mkdir(parents=True, exist_ok=True)
    text_path = text_dir / "workflow-route.txt"
    text_path.write_text(
        "--- Page 1 --- The paper uses numerical checks and survey analysis.",
        encoding="utf-8",
    )

    def fake_retrieve_publication_pdf(*args: Any, **kwargs: Any) -> PaperFile:
        session = args[0]
        candidate = kwargs["candidate"]
        publication = kwargs["publication"]
        paper = PaperFile(
            candidate_id=candidate.id,
            publication_id=publication.id,
            original_filename="workflow-route.pdf",
            stored_path="papers/test/workflow-route.pdf",
            sha256="8" * 64,
            size_bytes=512,
            page_count=1,
            parsed_text_path=str(text_path.relative_to(settings.project_root)),
            source_url="https://arxiv.org/pdf/2504.22222",
            license_note="arXiv public PDF.",
            text_quality_json="{}",
        )
        session.add(paper)
        session.flush()
        return paper

    provider = MockProvider(
        PaperAnalysisOutput(
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
        ),
    )
    monkeypatch.setattr(
        "app.services.research_workflow.retrieve_publication_pdf",
        fake_retrieve_publication_pdf,
    )
    monkeypatch.setattr("app.services.research_workflow.get_ai_provider", lambda: provider)
    monkeypatch.setattr(
        "app.services.research_workflow.load_research_portfolio_text_status",
        lambda: SimpleNamespace(
            available=True,
            text="magnetic fields computational astrophysics survey analysis",
            status="AVAILABLE",
            reason=None,
            cache_path="data/cache/portfolio_text/test.txt",
        ),
    )
    monkeypatch.setattr(
        "app.services.research_workflow.required_attachments_ready",
        lambda: True,
    )
    monkeypatch.setattr("app.services.drafting.required_attachments_ready", lambda _: True)

    response = client.post(
        "/candidates/1/research-workflow/run",
        data={"csrf": csrf_token()},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert str(response.url).endswith("/drafts/1/manual-review")
    assert "Magnetic Structures in Time-Domain Surveys" in response.text
    assert "Manual Outlook copy review" in response.text
    assert "Copy recipient" in response.text
    assert "Copy subject" in response.text
    assert "Copy email body" in response.text
    assert "Copy complete email" in response.text
    assert "Attach these two files manually in Outlook." in response.text
    assert "Select Publication" not in response.text


def test_run_research_workflow_does_not_render_selection_for_single_eligible_paper_pause(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    client, session_factory = build_test_context(tmp_path)
    with session_factory() as session:
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
            title="Single Eligible Arxiv Paper",
            title_fingerprint=title_fingerprint("Single Eligible Arxiv Paper"),
            year=2025,
            venue="Example Journal",
            doi="10.1000/single-eligible",
            arxiv_id="2504.33333",
            openalex_id="https://openalex.org/WSINGLE",
            source="openalex",
            open_access_url="https://arxiv.org/abs/2504.33333",
            pdf_url="https://arxiv.org/pdf/2504.33333",
            author_count=3,
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
                author_position=2,
                author_count=3,
                openalex_author_id="https://openalex.org/A1",
                confirmed_author_present=True,
                corresponding_author=False,
                role="middle_author",
                identity_confidence=0.95,
                match_status="MATCHED",
                score=91.0,
                connection_summary="magnetic fields",
                warnings_json="[]",
                score_details_json=(
                    '{"components":{"portfolio_similarity":30.0},'
                    '"reasons":["Portfolio similarity matched: magnetic fields.",'
                    '"Confirmed author appears at position 2.","Author count: 3.",'
                    '"Recent publication from 2025."]}'
                ),
            ),
        )
        session.commit()

    available = SimpleNamespace(
        available=True,
        text="magnetic fields computational astrophysics survey analysis",
        status="AVAILABLE",
        reason=None,
        cache_path="data/cache/portfolio_text/test.txt",
    )
    monkeypatch.setattr(
        "app.services.research_workflow.load_research_portfolio_text_status",
        lambda: available,
    )

    def failing_retrieve_publication_pdf(*args: Any, **kwargs: Any) -> PaperFile:
        raise ValueError("Synthetic PDF retrieval failure after automatic selection.")

    monkeypatch.setattr(
        "app.services.research_workflow.retrieve_publication_pdf",
        failing_retrieve_publication_pdf,
    )

    response = client.post(
        "/candidates/1/research-workflow/run",
        data={"csrf": csrf_token()},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert str(response.url).endswith("/candidates/1")
    assert "Select Publication" not in response.text
    assert "<h2>Select Publication</h2>" not in response.text
    assert "Single Eligible Arxiv Paper" in response.text
    with session_factory() as session:
        workflow = session.scalars(select(ResearchWorkflowRun)).one()
        assert workflow.status == "FAILED"
        assert "All automatically suitable publications failed" in (
            workflow.failure_reason or ""
        )
        assert "all_suitable_papers_exhausted" in workflow.retrieval_result_json


def test_fetch_publications_does_not_start_research_workflow(tmp_path: Path) -> None:
    client, session_factory = build_test_context(tmp_path)
    with session_factory() as session:
        candidate = create_candidate(
            session,
            full_name="Kevin Burdge",
            title="Assistant Professor",
            institution="MIT",
            department="Physics",
            research_area="compact binaries time-domain astrophysics",
            official_profile_url="https://physics.mit.edu/faculty/kevin-burdge/",
            notes=None,
        )
        candidate.openalex_author_id = "https://openalex.org/A5083946994"
        paper = Publication(
            title="Double White Dwarf Tides with Multi-messenger Measurements",
            title_fingerprint=title_fingerprint(
                "Double White Dwarf Tides with Multi-messenger Measurements",
            ),
            year=2025,
            venue="Example Journal",
            doi="10.1000/burdge-workflow-state",
            arxiv_id="2501.77777",
            openalex_id="https://openalex.org/WBURDGE777",
            source="openalex",
            open_access_url="https://arxiv.org/abs/2501.77777",
            pdf_url="https://arxiv.org/pdf/2501.77777",
            author_count=2,
            citation_count=12,
            work_type="article",
            metadata_json="{}",
        )
        session.add(paper)
        session.flush()
        session.add(
            Authorship(
                candidate_id=candidate.id,
                publication_id=paper.id,
                author_position=1,
                author_count=2,
                openalex_author_id="https://openalex.org/A5083946994",
                confirmed_author_present=True,
                corresponding_author=True,
                role="corresponding_author",
                identity_confidence=0.98,
                match_status="MATCHED",
                score=93.0,
                connection_summary="compact binaries and time-domain astrophysics",
                warnings_json="[]",
                score_details_json=(
                    '{"components":{"portfolio_similarity":32.0},'
                    '"reasons":["Portfolio similarity matched: compact binaries.",'
                    '"Confirmed author is corresponding author.","Author count: 2.",'
                    '"Recent publication from 2025."]}'
                ),
            ),
        )
        session.commit()

    fetched = client.post(
        "/candidates/1/publications/retrieve-live",
        data={"csrf": csrf_token()},
        follow_redirects=True,
    )
    detail = client.get("/candidates/1")

    assert fetched.status_code == 200
    assert str(fetched.url).endswith("/candidates/1/publications/select")
    assert "Double White Dwarf Tides with Multi-messenger Measurements" in fetched.text
    assert detail.status_code == 200
    assert "No workflow run yet" in detail.text
    assert "Waiting For Manual Paper Selection" not in detail.text
    with session_factory() as session:
        assert list(session.scalars(select(ResearchWorkflowRun))) == []


def test_legacy_pre_run_manual_workflow_is_displayed_as_not_started(tmp_path: Path) -> None:
    client, session_factory = build_test_context(tmp_path)
    with session_factory() as session:
        candidate = create_candidate(
            session,
            full_name="Kevin Burdge",
            title="Assistant Professor",
            institution="MIT",
            department="Physics",
            research_area="compact binaries time-domain astrophysics",
            official_profile_url="https://physics.mit.edu/faculty/kevin-burdge/",
            notes=None,
        )
        session.add(
            ResearchWorkflowRun(
                candidate_id=candidate.id,
                status="WAITING_FOR_MANUAL_PAPER_SELECTION",
                current_stage="Selecting next paper",
                failure_reason=(
                    "No publication passed the automatic suitability threshold. "
                    "Manual paper selection is required before PDF retrieval or analysis."
                ),
            ),
        )
        session.commit()

    detail = client.get("/candidates/1")

    assert detail.status_code == 200
    assert "No workflow run yet" in detail.text
    assert "Waiting For Manual Paper Selection" not in detail.text
    assert "No publication passed the automatic suitability threshold" not in detail.text


def test_research_workflow_waits_for_openalex_confirmation_then_resumes(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    client, session_factory = build_test_context(tmp_path)
    openalex_calls: list[str] = []

    with session_factory() as session:
        candidate = create_candidate(
            session,
            full_name="Kevin Burdge",
            title="Assistant Professor",
            institution="MIT",
            department="Physics",
            research_area="compact binaries time-domain astrophysics stellar dynamics",
            official_profile_url="https://physics.mit.edu/faculty/kevin-burdge/",
            notes=None,
        )
        add_email_address(
            session,
            candidate_id=candidate.id,
            email="burdge@mit.edu",
            source_url="https://physics.mit.edu/faculty/kevin-burdge/",
            source_type="official_faculty_profile",
            confidence="HIGH",
            verification_status="VERIFIED",
        )
        session.commit()

    class FakeOpenAlexClient:
        def search_author_candidates(self, candidate: Any) -> list[OpenAlexAuthorCandidate]:
            openalex_calls.append(f"author:{candidate.id}:{candidate.full_name}")
            return [
                OpenAlexAuthorCandidate(
                    openalex_id="https://openalex.org/A999999",
                    display_name="Kevin Burdge",
                    orcid=None,
                    institutions=["California Institute of Technology"],
                    works_count=30,
                    recent_works_count=6,
                    confidence=0.55,
                    reasons=["Exact author-name match."],
                    raw={},
                    current_institutions=["California Institute of Technology"],
                    previous_institutions=[],
                    topics=["Particle physics"],
                    profile_url="https://openalex.org/A999999",
                ),
                OpenAlexAuthorCandidate(
                    openalex_id="https://openalex.org/A123456",
                    display_name="Kevin Burdge",
                    orcid="https://orcid.org/0000-0002-0000-0000",
                    institutions=[
                        "Massachusetts Institute of Technology",
                        "California Institute of Technology",
                    ],
                    works_count=18,
                    recent_works_count=5,
                    confidence=0.93,
                    reasons=[
                        "Exact author-name match.",
                        "Current affiliation matches MIT.",
                        "OpenAlex topics overlap with the recorded research area.",
                    ],
                    raw={},
                    current_institutions=["Massachusetts Institute of Technology"],
                    previous_institutions=["California Institute of Technology"],
                    topics=["Astrophysics", "Compact binaries", "Stellar dynamics"],
                    profile_url="https://openalex.org/A123456",
                ),
            ]

        def works_for_author(
            self,
            openalex_author_id: str,
            *,
            from_year: int | None = None,
        ) -> list[PublicationMetadata]:
            openalex_calls.append(f"works:{openalex_author_id}:{from_year}")
            assert openalex_author_id == "https://openalex.org/A123456"
            return [
                PublicationMetadata(
                    title="Weak Fit Paper Without Full Text",
                    year=2025,
                    venue="Example Journal",
                    doi="10.1000/weak-fit",
                    arxiv_id=None,
                    openalex_id="https://openalex.org/WWEAK",
                    source="openalex",
                    open_access_url=None,
                    pdf_url=None,
                    authors=["Kevin Burdge"],
                    author_institutions=["Massachusetts Institute of Technology"],
                    raw={"_retrieval": {"source_url": "https://api.openalex.org/works"}},
                    citation_count=2,
                    work_type="article",
                    topics=["Unrelated instrumentation"],
                    author_openalex_ids=["https://openalex.org/A123456"],
                ),
                PublicationMetadata(
                    title="Compact Binary Discovery in Time-Domain Surveys",
                    year=2025,
                    venue="Example Astrophysics Journal",
                    doi="10.1000/workflow-confirmed",
                    arxiv_id="2502.12345",
                    openalex_id="https://openalex.org/WKEVIN",
                    source="openalex",
                    open_access_url="https://arxiv.org/abs/2502.12345",
                    pdf_url="https://arxiv.org/pdf/2502.12345",
                    authors=["K. Burdge", "Collaborator"],
                    author_institutions=["Massachusetts Institute of Technology"],
                    raw={"_retrieval": {"source_url": "https://api.openalex.org/works"}},
                    citation_count=12,
                    work_type="article",
                    topics=["Compact binaries", "Time-domain astrophysics"],
                    author_openalex_ids=[
                        "https://openalex.org/A123456",
                        "https://openalex.org/A999999",
                    ],
                    corresponding_author_positions={1},
                ),
            ]

    class FakeCrossrefClient:
        def work_by_doi(self, doi: str | None) -> PublicationMetadata | None:
            openalex_calls.append(f"crossref:{doi}")
            return None

    settings = get_settings()
    text_dir = settings.project_root / "data" / "cache" / "paper_text"
    text_dir.mkdir(parents=True, exist_ok=True)
    text_path = text_dir / "workflow-openalex-confirmation.txt"
    text_path.write_text(
        "--- Page 1 --- The paper uses time-domain survey analysis for compact binaries.",
        encoding="utf-8",
    )

    def fake_retrieve_publication_pdf(*args: Any, **kwargs: Any) -> PaperFile:
        session = args[0]
        candidate = kwargs["candidate"]
        publication = kwargs["publication"]
        assert publication.title == "Compact Binary Discovery in Time-Domain Surveys"
        paper = PaperFile(
            candidate_id=candidate.id,
            publication_id=publication.id,
            original_filename="workflow-openalex-confirmation.pdf",
            stored_path="papers/test/workflow-openalex-confirmation.pdf",
            sha256="7" * 64,
            size_bytes=512,
            page_count=1,
            parsed_text_path=str(text_path.relative_to(settings.project_root)),
            source_url="https://arxiv.org/pdf/2502.12345",
            license_note="arXiv public PDF.",
            text_quality_json="{}",
        )
        session.add(paper)
        session.flush()
        return paper

    provider = MockProvider(
        PaperAnalysisOutput(
            title="Compact Binary Discovery in Time-Domain Surveys",
            research_question="How do time-domain surveys find compact binaries?",
            motivation="The paper studies compact binary discovery.",
            methods="The paper uses time-domain survey analysis for compact binaries.",
            results="The paper reports a compact-binary discovery workflow.",
            overclaim_risks="Do not imply independent verification.",
            connection_to_arnav="scientific Python and survey analysis",
            confidence=0.86,
            evidence=[
                EvidenceClaim(
                    claim="the paper uses time-domain survey analysis",
                    evidence_text=(
                        "The paper uses time-domain survey analysis for compact binaries."
                    ),
                    page_number=1,
                    section_name="Extracted text",
                    classification=EvidenceClassification.EXPLICIT,
                    confidence=0.9,
                ),
            ],
        ),
    )

    monkeypatch.setattr("app.services.metadata.OpenAlexClient", FakeOpenAlexClient)
    monkeypatch.setattr("app.services.metadata.CrossrefClient", FakeCrossrefClient)
    monkeypatch.setattr(
        "app.services.metadata.load_research_portfolio_text",
        lambda: "compact binaries time-domain astrophysics stellar dynamics survey analysis",
    )
    monkeypatch.setattr(
        "app.services.metadata.load_research_portfolio_text_status",
        lambda: SimpleNamespace(
            available=True,
            text="compact binaries time-domain astrophysics stellar dynamics survey analysis",
            status="AVAILABLE",
            reason=None,
            cache_path="data/cache/portfolio_text/test.txt",
        ),
    )
    monkeypatch.setattr(
        "app.services.research_workflow.load_research_portfolio_text_status",
        lambda: SimpleNamespace(
            available=True,
            text="compact binaries time-domain astrophysics stellar dynamics survey analysis",
            status="AVAILABLE",
            reason=None,
            cache_path="data/cache/portfolio_text/test.txt",
        ),
    )
    monkeypatch.setattr(
        "app.services.research_workflow.retrieve_publication_pdf",
        fake_retrieve_publication_pdf,
    )
    monkeypatch.setattr("app.services.research_workflow.get_ai_provider", lambda: provider)
    monkeypatch.setattr(
        "app.services.research_workflow.required_attachments_ready",
        lambda: True,
    )
    monkeypatch.setattr("app.services.drafting.required_attachments_ready", lambda _: True)

    confirmation = client.post(
        "/candidates/1/research-workflow/run",
        data={"csrf": csrf_token()},
        follow_redirects=True,
    )

    assert confirmation.status_code == 200
    assert "/candidates/1/publications/openalex-author/confirm?resume_workflow=1" in str(
        confirmation.url,
    )
    assert "Confirm OpenAlex Author" in confirmation.text
    assert "Confirm OpenAlex author" in confirmation.text
    assert "Works count: 18" in confirmation.text
    assert "Recent publication count: 5" in confirmation.text
    assert "Massachusetts Institute of Technology" in confirmation.text
    assert "Matching explanation" in confirmation.text
    assert "Current affiliation matches MIT." in confirmation.text
    assert "value=\"https://openalex.org/A123456\"" in confirmation.text
    assert "checked" in confirmation.text
    assert "Select Publication" not in confirmation.text
    assert "Approve paper" not in confirmation.text

    with session_factory() as session:
        waiting = session.scalars(select(ResearchWorkflowRun)).one()
        waiting_workflow_id = waiting.id
        assert waiting.status == "WAITING_FOR_AUTHOR_CONFIRMATION"
        assert waiting.failed_stage is None
        assert waiting.current_stage == "Finding publications"
    assert f"workflow_id={waiting_workflow_id}" in str(confirmation.url)
    assert f'name="workflow_id" value="{waiting_workflow_id}"' in confirmation.text

    resumed = client.post(
        "/candidates/1/publications/openalex-author/confirm",
        data={
            "csrf": csrf_token(),
            "selected_openalex_author_id": "https://openalex.org/A123456",
            "resume_workflow": "1",
            "workflow_id": str(waiting_workflow_id),
        },
        follow_redirects=True,
    )

    assert resumed.status_code == 200
    assert str(resumed.url).endswith("/drafts/1/manual-review")
    assert "Manual Outlook copy review" in resumed.text
    assert "Compact Binary Discovery in Time-Domain Surveys" in resumed.text
    assert "Weak Fit Paper Without Full Text" not in resumed.text
    assert "Select Publication" not in resumed.text
    assert "Approve paper" not in resumed.text
    assert "works:https://openalex.org/A123456:2021" in openalex_calls
    assert "crossref:10.1000/workflow-confirmed" in openalex_calls

    with session_factory() as session:
        stored_candidate = session.get(Candidate, 1)
        assert stored_candidate is not None
        assert stored_candidate.openalex_author_id == "https://openalex.org/A123456"
        workflows = list(session.scalars(select(ResearchWorkflowRun)))
        assert len(workflows) == 1
        workflow = workflows[0]
        assert workflow.id == waiting_workflow_id
        assert workflow.status == "READY_FOR_REVIEW"
        assert workflow.selected_publication_id is not None
        assert workflow.paper_file_id is not None
        assert workflow.analysis_id is not None
        assert workflow.draft_id is not None
        selected = session.get(Publication, workflow.selected_publication_id)
        assert selected is not None
        assert selected.title == "Compact Binary Discovery in Time-Domain Surveys"


def test_author_confirmation_waits_for_portfolio_without_manual_selection(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    client, session_factory = build_test_context(tmp_path)
    with session_factory() as session:
        create_candidate(
            session,
            full_name="Kevin Burdge",
            title="Assistant Professor",
            institution="MIT",
            department="Physics",
            research_area="compact binaries time-domain astrophysics",
            official_profile_url="https://physics.mit.edu/faculty/kevin-burdge/",
            notes=None,
        )
        add_email_address(
            session,
            candidate_id=1,
            email="kevin@example.mit.edu",
            source_url="https://physics.mit.edu/faculty/kevin-burdge/",
            source_type="official_university_page",
            confidence="HIGH",
            verification_status="VERIFIED",
        )
        session.commit()

    calls: list[str] = []

    class FakeOpenAlexClient:
        def search_author_candidates(self, candidate: Candidate) -> list[OpenAlexAuthorCandidate]:
            calls.append(f"authors:{candidate.full_name}")
            return [
                OpenAlexAuthorCandidate(
                    openalex_id="https://openalex.org/A123456",
                    display_name="Kevin Burdge",
                    orcid=None,
                    institutions=["Massachusetts Institute of Technology"],
                    works_count=94,
                    recent_works_count=12,
                    confidence=0.9,
                    reasons=["Current affiliation matches MIT."],
                    raw={},
                    current_institutions=["Massachusetts Institute of Technology"],
                    previous_institutions=["California Institute of Technology"],
                    topics=["Astrophysics", "Compact binaries"],
                    profile_url="https://openalex.org/A123456",
                ),
            ]

        def works_for_author(
            self,
            openalex_author_id: str,
            *,
            from_year: int | None = None,
        ) -> list[PublicationMetadata]:
            calls.append(f"works:{openalex_author_id}:{from_year}")
            return [
                PublicationMetadata(
                    title="Compact Binary Discovery in Time-Domain Surveys",
                    year=2025,
                    venue="Astrophysical Journal",
                    doi="10.1000/waiting-portfolio",
                    arxiv_id="2502.12345",
                    openalex_id="https://openalex.org/W123",
                    source="openalex",
                    open_access_url="https://arxiv.org/abs/2502.12345",
                    pdf_url="https://arxiv.org/pdf/2502.12345",
                    authors=["Kevin Burdge", "Jane Doe"],
                    author_institutions=["Massachusetts Institute of Technology"],
                    raw={},
                    citation_count=12,
                    work_type="article",
                    abstract_text="A time-domain survey analysis for compact binaries.",
                    topics=["Astrophysics", "Compact binaries"],
                    author_openalex_ids=["https://openalex.org/A123456", "https://openalex.org/A2"],
                ),
            ]

    class FakeCrossrefClient:
        def work_by_doi(self, doi: str | None) -> PublicationMetadata | None:
            calls.append(f"crossref:{doi}")
            return None

    settings = get_settings()
    unavailable = SimpleNamespace(
        available=False,
        text="",
        status="PORTFOLIO_INPUT_UNAVAILABLE",
        reason=(
            "Research portfolio PDF is missing at "
            "/data/private_assets/arnav_research_portfolio.pdf."
        ),
        cache_path=None,
    )
    monkeypatch.setattr("app.services.metadata.OpenAlexClient", FakeOpenAlexClient)
    monkeypatch.setattr("app.services.metadata.CrossrefClient", FakeCrossrefClient)
    monkeypatch.setattr(
        "app.services.metadata.load_research_portfolio_text_status",
        lambda: unavailable,
    )
    monkeypatch.setattr(
        "app.services.research_workflow.load_research_portfolio_text_status",
        lambda: unavailable,
    )

    confirmation = client.post(
        "/candidates/1/research-workflow/run",
        data={"csrf": csrf_token()},
        follow_redirects=True,
    )
    assert confirmation.status_code == 200
    assert "Confirm OpenAlex Author" in confirmation.text

    response = client.post(
        "/candidates/1/publications/openalex-author/confirm",
        data={
            "csrf": csrf_token(),
            "selected_openalex_author_id": "https://openalex.org/A123456",
            "resume_workflow": "1",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert str(response.url).endswith("/candidates/1")
    assert "Waiting For Portfolio Input" in response.text
    assert "PORTFOLIO_INPUT_UNAVAILABLE" in response.text
    assert "Open secure setup" in response.text
    assert "Select Publication" not in response.text
    assert "Approve paper" not in response.text
    assert "works:https://openalex.org/A123456:2021" in calls

    with session_factory() as session:
        workflows = list(session.scalars(select(ResearchWorkflowRun)))
        assert len(workflows) == 1
        assert workflows[0].status == "WAITING_FOR_PORTFOLIO_INPUT"
        assert workflows[0].selected_publication_id is None

    text_dir = settings.project_root / "data" / "cache" / "paper_text"
    text_dir.mkdir(parents=True, exist_ok=True)
    text_path = text_dir / "workflow-portfolio-resume.txt"
    text_path.write_text(
        "--- Page 1 --- The paper uses time-domain survey analysis for compact binaries.",
        encoding="utf-8",
    )

    def fake_retrieve_publication_pdf(*args: Any, **kwargs: Any) -> PaperFile:
        session = args[0]
        candidate = kwargs["candidate"]
        publication = kwargs["publication"]
        paper = PaperFile(
            candidate_id=candidate.id,
            publication_id=publication.id,
            original_filename="workflow-portfolio-resume.pdf",
            stored_path="papers/test/workflow-portfolio-resume.pdf",
            sha256="8" * 64,
            size_bytes=512,
            page_count=1,
            parsed_text_path=str(text_path.relative_to(settings.project_root)),
            source_url="https://arxiv.org/pdf/2502.12345",
            license_note="arXiv public PDF.",
            text_quality_json="{}",
        )
        session.add(paper)
        session.flush()
        return paper

    provider = MockProvider(
        PaperAnalysisOutput(
            title="Compact Binary Discovery in Time-Domain Surveys",
            research_question="How do time-domain surveys find compact binaries?",
            motivation="The paper studies compact binary discovery.",
            methods="The paper uses time-domain survey analysis for compact binaries.",
            results="The paper reports a compact-binary discovery workflow.",
            overclaim_risks="Do not imply independent verification.",
            connection_to_arnav="scientific Python and survey analysis",
            confidence=0.86,
            evidence=[
                EvidenceClaim(
                    claim="the paper uses time-domain survey analysis",
                    evidence_text=(
                        "The paper uses time-domain survey analysis for compact binaries."
                    ),
                    page_number=1,
                    section_name="Extracted text",
                    classification=EvidenceClassification.EXPLICIT,
                    confidence=0.9,
                ),
            ],
        ),
    )
    available = SimpleNamespace(
        available=True,
        text="compact binaries time-domain astrophysics stellar dynamics survey analysis",
        status="AVAILABLE",
        reason=None,
        cache_path="data/cache/portfolio_text/test.txt",
    )
    monkeypatch.setattr(
        "app.services.metadata.load_research_portfolio_text_status",
        lambda: available,
    )
    monkeypatch.setattr(
        "app.services.research_workflow.load_research_portfolio_text_status",
        lambda: available,
    )
    monkeypatch.setattr(
        "app.services.research_workflow.retrieve_publication_pdf",
        fake_retrieve_publication_pdf,
    )
    monkeypatch.setattr("app.services.research_workflow.get_ai_provider", lambda: provider)
    monkeypatch.setattr("app.services.research_workflow.required_attachments_ready", lambda: True)
    monkeypatch.setattr("app.services.drafting.required_attachments_ready", lambda _: True)

    resumed = client.post(
        "/candidates/1/research-workflow/resume",
        data={"csrf": csrf_token()},
        follow_redirects=True,
    )

    assert resumed.status_code == 200
    assert str(resumed.url).endswith("/drafts/1/manual-review")
    assert "Manual Outlook copy review" in resumed.text
    assert "Select Publication" not in resumed.text
    assert "Approve paper" not in resumed.text

    with session_factory() as session:
        workflows = list(session.scalars(select(ResearchWorkflowRun)))
        assert len(workflows) == 1
        assert workflows[0].status == "READY_FOR_REVIEW"
        assert workflows[0].draft_id is not None


def test_publication_linked_analysis_requires_paper_approval(tmp_path: Path) -> None:
    client, session_factory = build_test_context(tmp_path)
    with session_factory() as session:
        candidate = create_candidate(
            session,
            full_name="Professor Jane Doe",
            title=None,
            institution="Example University",
            department=None,
            research_area="cosmology data analysis",
            official_profile_url=None,
            notes=None,
        )
        publication = Publication(
            title="Cosmology With Public Survey Data",
            title_fingerprint=title_fingerprint("Cosmology With Public Survey Data"),
            year=2024,
            venue="Example Journal",
            doi=None,
            arxiv_id="2401.12345",
            openalex_id=None,
            source="manual",
            open_access_url=None,
            pdf_url=None,
            author_count=2,
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
                role="first_author",
                identity_confidence=0.9,
                match_status="MATCHED",
                score=75.0,
                connection_summary="Cosmology data analysis matches.",
                warnings_json="[]",
            ),
        )
        session.add(
            PaperFile(
                candidate_id=candidate.id,
                publication_id=publication.id,
                original_filename="paper.pdf",
                stored_path="papers/test/paper.pdf",
                sha256="a" * 64,
                size_bytes=128,
                page_count=1,
                parsed_text_path=None,
                source_url="https://arxiv.org/pdf/2401.12345",
                license_note="arXiv public PDF.",
                text_quality_json="{}",
            ),
        )
        session.commit()

    blocked = client.post(
        "/papers/1/analysis",
        data={
            "csrf": csrf_token(),
            "title": "cosmology",
            "research_question": "Question",
            "methods": "Methods",
            "results": "Results",
            "connection_to_arnav": "Connection",
            "claim": "Claim",
            "evidence_text": "Evidence",
            "page_number": "1",
            "section_name": "Methods",
            "classification": "EXPLICIT",
            "confidence": "0.8",
        },
    )

    assert blocked.status_code == 400
    assert "Approve this paper" in blocked.text


def test_ai_analysis_missing_key_returns_clear_error_without_fake_analysis(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("AI_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    get_settings.cache_clear()
    client, session_factory = build_test_context(tmp_path)
    settings = get_settings()
    text_dir = settings.project_root / "data" / "cache" / "paper_text"
    text_dir.mkdir(parents=True, exist_ok=True)
    text_path = text_dir / "missing-key-route.txt"
    text_path.write_text(
        "--- Page 1 --- We use numerical simulation to test magnetic structures.",
        encoding="utf-8",
    )
    with session_factory() as session:
        candidate = create_candidate(
            session,
            full_name="Professor Jane Doe",
            title=None,
            institution="Example University",
            department=None,
            research_area="computational physics",
            official_profile_url=None,
            notes=None,
        )
        session.add(
            PaperFile(
                candidate_id=candidate.id,
                publication_id=None,
                original_filename="paper.pdf",
                stored_path="papers/test/paper.pdf",
                sha256="b" * 64,
                size_bytes=128,
                page_count=1,
                parsed_text_path=str(text_path.relative_to(settings.project_root)),
                source_url=None,
                license_note=None,
                text_quality_json="{}",
            ),
        )
        session.commit()

    response = client.post(
        "/papers/1/ai-analysis",
        data={
            "csrf": csrf_token(),
            "title": "Magnetic structures",
            "connection_to_arnav": "Parker Solar Probe magnetic-field analysis",
        },
    )
    with session_factory() as session:
        analysis_count = len(list(session.scalars(select(PaperAnalysis))))

    assert response.status_code == 400
    assert "Gemini API key is missing" in response.text
    assert analysis_count == 0
    get_settings.cache_clear()


def test_discovery_homepage_requires_directory_approval(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    homepage_html = """
    <nav>
      <a href="/faculty/">Faculty Directory</a>
      <a href="/graduate-program/">Graduate Program</a>
      <a href="/undergraduate-program/">Undergraduate Program</a>
    </nav>
    <main>
      <h1>MIT Physics</h1>
      <a href="/graduate-program/">Graduate Program</a>
      <a href="/undergraduate-program/">Undergraduate Program</a>
    </main>
    """
    faculty_html = """
    <main>
      <section class="faculty-card">
        <h3><a href="/faculty/tracy-slatyer/">Tracy Slatyer</a></h3>
        <p>
          Professor of Physics. Research focuses on dark matter
          and analysis of astrophysical datasets.
        </p>
        <p>Email: tslatyer@example.edu</p>
      </section>
    </main>
    """

    class FakeFetcher:
        def fetch(self, url: str, *, expected: str = "html") -> FetchResult:
            body = faculty_html if url.endswith("/faculty/") else homepage_html
            final_url = "https://physics.mit.edu/faculty/" if url.endswith("/faculty/") else url
            return FetchResult(
                url=url,
                final_url=final_url,
                status_code=200,
                content_type="text/html",
                body=body.encode("utf-8"),
                sha256="c" * 64,
                robots_allowed=True,
            )

    monkeypatch.setattr("app.routes.discovery.SafeFetcher", FakeFetcher)
    client = build_test_client(tmp_path)

    resolve = client.post(
        "/discovery/resolve",
        data={
            "csrf": csrf_token(),
            "source_url": "https://physics.mit.edu/",
            "institution": "MIT",
            "department": "Physics",
        },
    )

    assert resolve.status_code == 200
    assert "Approve Directory Page" in resolve.text
    assert "https://physics.mit.edu/faculty/" in resolve.text
    assert "Graduate Program Undergraduate Program" not in resolve.text

    imported = client.post(
        "/discovery/import",
        data={
            "csrf": csrf_token(),
            "source_url": "https://physics.mit.edu/",
            "directory_url": "https://physics.mit.edu/faculty/",
            "institution": "MIT",
            "department": "Physics",
        },
        follow_redirects=True,
    )

    assert imported.status_code == 200
    assert "Tracy Slatyer" in imported.text
    assert "Ranking explanation" in imported.text
    assert "Source URL" in imported.text
    assert "Source element" in imported.text


def test_mit_discovery_save_then_fetch_publications_for_kevin_burdge(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    homepage_html = """
    <nav>
      <a href="/faculty/">Faculty</a>
      <a href="/graduate-program/">Graduate Program</a>
    </nav>
    <main><h1>MIT Physics</h1><a href="/faculty/">Faculty Directory</a></main>
    """
    faculty_html = """
    <main>
      <section class="faculty-card">
        <h3><a href="/faculty/kevin-burdge/">Kevin Burdge</a></h3>
        <p>Assistant Professor of Physics.</p>
        <p>
          Research: computational time-domain astrophysics, compact binaries,
          stellar dynamics, and astronomical data analysis.
        </p>
        <p>Email: kburdge@example.edu</p>
      </section>
    </main>
    """
    openalex_calls: list[str] = []

    class FakeFetcher:
        def fetch(self, url: str, *, expected: str = "html") -> FetchResult:
            assert expected == "html"
            if url.endswith("/faculty/"):
                return FetchResult(
                    url=url,
                    final_url="https://physics.mit.edu/faculty/",
                    status_code=200,
                    content_type="text/html",
                    body=faculty_html.encode("utf-8"),
                    sha256="f" * 64,
                    robots_allowed=True,
                )
            return FetchResult(
                url=url,
                final_url="https://physics.mit.edu/",
                status_code=200,
                content_type="text/html",
                body=homepage_html.encode("utf-8"),
                sha256="e" * 64,
                robots_allowed=True,
            )

    class FakeOpenAlexClient:
        def search_author_candidates(self, candidate: Any) -> list[OpenAlexAuthorCandidate]:
            openalex_calls.append(f"author:{candidate.id}:{candidate.full_name}")
            return [
                OpenAlexAuthorCandidate(
                    openalex_id="https://openalex.org/A123456",
                    display_name="Kevin Burdge",
                    orcid=None,
                    institutions=["Massachusetts Institute of Technology"],
                    works_count=12,
                    recent_works_count=4,
                    confidence=0.95,
                    reasons=["Name and institution matched MIT Physics candidate."],
                    raw={},
                ),
            ]

        def works_for_author(
            self,
            openalex_author_id: str,
            *,
            from_year: int | None = None,
        ) -> list[PublicationMetadata]:
            openalex_calls.append(f"works:{openalex_author_id}:{from_year}")
            return [
                PublicationMetadata(
                    title="Relativistic Binary Evolution in Time-Domain Surveys",
                    year=2025,
                    venue="Example Astrophysics Journal",
                    doi="10.1000/burdge",
                    arxiv_id="2501.12345",
                    openalex_id="https://openalex.org/WBURDGE",
                    source="openalex",
                    open_access_url="https://arxiv.org/abs/2501.12345",
                    pdf_url="https://arxiv.org/pdf/2501.12345",
                    authors=["Kevin Burdge", "Other Person"],
                    author_institutions=["Massachusetts Institute of Technology"],
                    raw={"_retrieval": {"source_url": "https://api.openalex.org/works"}},
                ),
            ]

    class FakeCrossrefClient:
        def work_by_doi(self, doi: str | None) -> PublicationMetadata | None:
            openalex_calls.append(f"crossref:{doi}")
            return None

    monkeypatch.setattr("app.routes.discovery.SafeFetcher", FakeFetcher)
    monkeypatch.setattr("app.services.metadata.OpenAlexClient", FakeOpenAlexClient)
    monkeypatch.setattr("app.services.metadata.CrossrefClient", FakeCrossrefClient)
    client = build_test_client(tmp_path)

    resolved = client.post(
        "/discovery/resolve",
        data={
            "csrf": csrf_token(),
            "source_url": "https://physics.mit.edu/",
            "institution": "MIT",
            "department": "Physics",
        },
    )
    assert resolved.status_code == 200
    assert "https://physics.mit.edu/faculty/" in resolved.text

    imported = client.post(
        "/discovery/import",
        data={
            "csrf": csrf_token(),
            "source_url": "https://physics.mit.edu/",
            "directory_url": "https://physics.mit.edu/faculty/",
            "institution": "MIT",
            "department": "Physics",
        },
        follow_redirects=True,
    )
    assert imported.status_code == 200
    assert "Kevin Burdge" in imported.text

    saved = client.post(
        "/discovery/candidates/1/save",
        data={"csrf": csrf_token()},
        follow_redirects=True,
    )
    assert saved.status_code == 200
    assert "Kevin Burdge" in saved.text
    assert "Fetch Publications" in saved.text

    publication_hub = client.get("/publications")
    assert publication_hub.status_code == 200
    assert "Kevin Burdge" in publication_hub.text
    assert "Fetch Publications" in publication_hub.text
    assert "Relativistic Binary Evolution" not in publication_hub.text

    fetched = client.post(
        "/candidates/1/publications/retrieve-live",
        data={"csrf": csrf_token()},
        follow_redirects=True,
    )
    publication_hub_after = client.get("/publications")

    assert fetched.status_code == 200
    assert "Relativistic Binary Evolution in Time-Domain Surveys" in fetched.text
    assert "Relativistic Binary Evolution in Time-Domain Surveys" in publication_hub_after.text
    assert "author:1:Kevin Burdge" in openalex_calls
    assert "works:https://openalex.org/A123456:2021" in openalex_calls
    assert "crossref:10.1000/burdge" in openalex_calls


def test_mit_kevin_burdge_openalex_author_confirmation_fetches_publications(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    homepage_html = """
    <nav>
      <a href="/faculty/">Faculty</a>
      <a href="/graduate-program/">Graduate Program</a>
    </nav>
    <main><h1>MIT Physics</h1><a href="/faculty/">Faculty Directory</a></main>
    """
    faculty_html = """
    <main>
      <section class="faculty-card">
        <h3><a href="/faculty/kevin-burdge/">Kevin Burdge</a></h3>
        <p>Assistant Professor of Physics.</p>
        <p>Research: time-domain astrophysics, compact binaries, and stellar dynamics.</p>
      </section>
    </main>
    """
    openalex_calls: list[str] = []

    class FakeFetcher:
        def fetch(self, url: str, *, expected: str = "html") -> FetchResult:
            assert expected == "html"
            if url.endswith("/faculty/"):
                return FetchResult(
                    url=url,
                    final_url="https://physics.mit.edu/faculty/",
                    status_code=200,
                    content_type="text/html",
                    body=faculty_html.encode("utf-8"),
                    sha256="b" * 64,
                    robots_allowed=True,
                )
            return FetchResult(
                url=url,
                final_url="https://physics.mit.edu/",
                status_code=200,
                content_type="text/html",
                body=homepage_html.encode("utf-8"),
                sha256="a" * 64,
                robots_allowed=True,
            )

    class FakeOpenAlexClient:
        def search_author_candidates(self, candidate: Any) -> list[OpenAlexAuthorCandidate]:
            openalex_calls.append(f"author:{candidate.id}:{candidate.full_name}")
            return [
                OpenAlexAuthorCandidate(
                    openalex_id="https://openalex.org/A999999",
                    display_name="Kevin Burdge",
                    orcid=None,
                    institutions=["California Institute of Technology"],
                    works_count=30,
                    recent_works_count=6,
                    confidence=0.55,
                    reasons=["Exact author-name match."],
                    raw={},
                    current_institutions=["California Institute of Technology"],
                    previous_institutions=[],
                    topics=["Particle physics"],
                    profile_url="https://openalex.org/A999999",
                ),
                OpenAlexAuthorCandidate(
                    openalex_id="https://openalex.org/A123456",
                    display_name="Kevin Burdge",
                    orcid="https://orcid.org/0000-0002-0000-0000",
                    institutions=[
                        "Massachusetts Institute of Technology",
                        "California Institute of Technology",
                    ],
                    works_count=18,
                    recent_works_count=5,
                    confidence=0.93,
                    reasons=[
                        "Exact author-name match.",
                        "Current affiliation matches MIT.",
                        "OpenAlex topics overlap with the recorded research area.",
                    ],
                    raw={},
                    current_institutions=["Massachusetts Institute of Technology"],
                    previous_institutions=["California Institute of Technology"],
                    topics=["Astrophysics", "Compact binaries", "Stellar dynamics"],
                    profile_url="https://openalex.org/A123456",
                ),
            ]

        def works_for_author(
            self,
            openalex_author_id: str,
            *,
            from_year: int | None = None,
        ) -> list[PublicationMetadata]:
            openalex_calls.append(f"works:{openalex_author_id}:{from_year}")
            assert openalex_author_id == "https://openalex.org/A123456"
            return [
                PublicationMetadata(
                    title="Compact Binary Discovery in Time-Domain Surveys",
                    year=2025,
                    venue="Example Astrophysics Journal",
                    doi="10.1000/kevin-confirmed",
                    arxiv_id="2502.12345",
                    openalex_id="https://openalex.org/WKEVIN",
                    source="openalex",
                    open_access_url="https://arxiv.org/abs/2502.12345",
                    pdf_url="https://arxiv.org/pdf/2502.12345",
                    authors=["K. Burdge", "Collaborator"],
                    author_institutions=["Massachusetts Institute of Technology"],
                    raw={"_retrieval": {"source_url": "https://api.openalex.org/works"}},
                    citation_count=12,
                    work_type="review",
                    topics=["Compact binaries", "Time-domain astrophysics"],
                    author_openalex_ids=[
                        "https://openalex.org/A123456",
                        "https://openalex.org/A999999",
                    ],
                    corresponding_author_positions={1},
                ),
            ]

    class FakeCrossrefClient:
        def work_by_doi(self, doi: str | None) -> PublicationMetadata | None:
            openalex_calls.append(f"crossref:{doi}")
            return None

    monkeypatch.setattr("app.routes.discovery.SafeFetcher", FakeFetcher)
    monkeypatch.setattr("app.services.metadata.OpenAlexClient", FakeOpenAlexClient)
    monkeypatch.setattr("app.services.metadata.CrossrefClient", FakeCrossrefClient)
    monkeypatch.setattr(
        "app.services.metadata.load_research_portfolio_text",
        lambda: "compact binaries time-domain astrophysics stellar dynamics survey analysis",
    )
    monkeypatch.setattr(
        "app.services.metadata.load_research_portfolio_text_status",
        lambda: SimpleNamespace(
            available=True,
            text="compact binaries time-domain astrophysics stellar dynamics survey analysis",
            status="AVAILABLE",
            reason=None,
            cache_path="data/cache/portfolio_text/test.txt",
        ),
    )
    client, session_factory = build_test_context(tmp_path)

    resolved = client.post(
        "/discovery/resolve",
        data={
            "csrf": csrf_token(),
            "source_url": "https://physics.mit.edu/",
            "institution": "MIT",
            "department": "Physics",
        },
    )
    assert resolved.status_code == 200
    assert "https://physics.mit.edu/faculty/" in resolved.text

    imported = client.post(
        "/discovery/import",
        data={
            "csrf": csrf_token(),
            "source_url": "https://physics.mit.edu/",
            "directory_url": "https://physics.mit.edu/faculty/",
            "institution": "MIT",
            "department": "Physics",
        },
        follow_redirects=True,
    )
    assert imported.status_code == 200
    assert "Kevin Burdge" in imported.text

    saved = client.post(
        "/discovery/candidates/1/save",
        data={"csrf": csrf_token()},
        follow_redirects=True,
    )
    assert saved.status_code == 200

    selection = client.post(
        "/candidates/1/publications/retrieve-live",
        data={"csrf": csrf_token()},
    )
    assert selection.status_code == 200
    assert "application/json" not in selection.headers["content-type"]
    assert "Confirm OpenAlex Author" in selection.text
    assert "Massachusetts Institute of Technology" in selection.text
    assert "California Institute of Technology" in selection.text
    assert "Astrophysics" in selection.text
    assert "https://orcid.org/0000-0002-0000-0000" in selection.text
    assert "https://openalex.org/A123456" in selection.text
    assert "Recent publication count: 5" in selection.text
    assert "value=\"https://openalex.org/A123456\"" in selection.text
    assert "checked" in selection.text
    assert "Compact Binary Discovery" not in selection.text

    confirmed = client.post(
        "/candidates/1/publications/openalex-author/confirm",
        data={
            "csrf": csrf_token(),
            "selected_openalex_author_id": "https://openalex.org/A123456",
        },
        follow_redirects=True,
    )
    publication_hub = client.get("/publications")

    assert confirmed.status_code == 200
    assert str(confirmed.url).endswith("/candidates/1/publications/select")
    assert "Select Publication" in confirmed.text
    assert "Compact Binary Discovery in Time-Domain Surveys" in confirmed.text
    assert "Position 1" in confirmed.text
    assert "Confirmed author: present" in confirmed.text
    assert "Corresponding author" in confirmed.text
    assert "Overall Score" in confirmed.text
    assert "Portfolio similarity matched" in confirmed.text
    assert "Review article bonus applied." in confirmed.text
    assert "Citation count: 12." in confirmed.text
    assert "Compact Binary Discovery in Time-Domain Surveys" in publication_hub.text
    assert "works:https://openalex.org/A123456:2021" in openalex_calls
    assert "crossref:10.1000/kevin-confirmed" in openalex_calls

    with session_factory() as session:
        stored = session.get(Candidate, 1)
        assert stored is not None
        assert stored.openalex_author_id == "https://openalex.org/A123456"
        stored_authorship = session.scalars(select(Authorship)).one()
        assert stored_authorship.openalex_author_id == "https://openalex.org/A123456"
        assert stored_authorship.author_position == 1
        assert stored_authorship.author_count == 2
        assert stored_authorship.confirmed_author_present is True
        assert stored_authorship.corresponding_author is True
        assert stored_authorship.role == "corresponding_author"
        assert stored_authorship.match_status == "MATCHED"
        assert stored_authorship.score >= 80
        assert "Candidate name was not found" not in stored_authorship.warnings_json

    openalex_calls.clear()
    refetched = client.post(
        "/candidates/1/publications/retrieve-live",
        data={"csrf": csrf_token()},
        follow_redirects=True,
    )

    assert refetched.status_code == 200
    assert str(refetched.url).endswith("/candidates/1/publications/select")
    assert "Confirm OpenAlex Author" not in refetched.text
    assert "Compact Binary Discovery in Time-Domain Surveys" in refetched.text
    assert "author:1:Kevin Burdge" not in openalex_calls
    assert "works:https://openalex.org/A123456:2021" not in openalex_calls


def test_discovery_exclusion_requires_manual_override(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    faculty_html = """
    <main>
      <section class="faculty-card">
        <h3><a href="/faculty/retired-person/">Retired Person</a></h3>
        <div class="faculty-card__job-title">Professor of Physics, Emeritus</div>
        <p>Retired experimental hardware instrumentation researcher.</p>
      </section>
    </main>
    """

    class FakeFetcher:
        def fetch(self, url: str, *, expected: str = "html") -> FetchResult:
            return FetchResult(
                url=url,
                final_url="https://physics.example.edu/faculty/",
                status_code=200,
                content_type="text/html",
                body=faculty_html.encode("utf-8"),
                sha256="d" * 64,
                robots_allowed=True,
            )

    monkeypatch.setattr("app.routes.discovery.SafeFetcher", FakeFetcher)
    client = build_test_client(tmp_path)

    imported = client.post(
        "/discovery/import",
        data={
            "csrf": csrf_token(),
            "source_url": "https://physics.example.edu/faculty/",
            "institution": "Example University",
            "department": "Physics",
        },
        follow_redirects=True,
    )

    assert imported.status_code == 200
    assert "Retired Person" in imported.text
    assert "Excluded:" in imported.text
    assert "Override exclusion" in imported.text

    blocked = client.post(
        "/discovery/candidates/1/save",
        data={"csrf": csrf_token()},
        follow_redirects=False,
    )
    assert blocked.status_code == 400

    override = client.post(
        "/discovery/candidates/1/override",
        data={"csrf": csrf_token()},
        follow_redirects=True,
    )
    assert override.status_code == 200
    assert "Manual override" in override.text

    saved = client.post(
        "/discovery/candidates/1/save",
        data={"csrf": csrf_token()},
        follow_redirects=True,
    )
    assert saved.status_code == 200
    assert "Retired Person" in saved.text


def test_dashboard_uses_real_workflow_counts(tmp_path: Path) -> None:
    client = build_test_client(tmp_path)
    client.post(
        "/candidates",
        data={"csrf": csrf_token(), "full_name": "Professor Jane Doe"},
    )

    response = client.get("/")

    assert response.status_code == 200
    assert "One draft, end to end" in response.text
    assert "Start Outreach" in response.text
