from collections.abc import Generator
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import create_engine_for_url, get_db, initialize_database
from app.main import create_app
from app.security.csrf import csrf_token
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
    assert "Source URL" in imported.text
    assert "Source element" in imported.text
