from collections.abc import Generator
from pathlib import Path
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
from app.security.csrf import csrf_token
from app.services.candidates import create_candidate
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
    assert "Do not send" in draft_response.text


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

    detail = client.get("/candidates/1")
    assert "Approve paper" in detail.text
    assert "Retrieve PDF" not in detail.text

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

    def fake_retrieve_publication_pdf(*args: Any, **kwargs: Any) -> None:
        called.append(1)

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
    assert called == [1]


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
                    openalex_id="https://openalex.org/AKEVIN",
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
    assert "works:https://openalex.org/AKEVIN:2021" in openalex_calls
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
                    authors=["Kevin Burdge", "Collaborator"],
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
    assert "Compact Binary Discovery in Time-Domain Surveys" in publication_hub.text
    assert "works:https://openalex.org/A123456:2021" in openalex_calls
    assert "crossref:10.1000/kevin-confirmed" in openalex_calls

    with session_factory() as session:
        stored = session.get(Candidate, 1)
        assert stored is not None
        assert stored.openalex_author_id == "https://openalex.org/A123456"
        stored_authorship = session.scalars(select(Authorship)).one()
        assert stored_authorship.openalex_author_id == "https://openalex.org/A123456"

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
    assert "Workflow Dashboard" in response.text
    assert "Import Department" in response.text
    assert "Candidates shortlisted" in response.text
    assert "Missing email" in response.text
