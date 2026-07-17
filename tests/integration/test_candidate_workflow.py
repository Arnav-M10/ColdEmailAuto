from collections.abc import Generator
from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import create_engine_for_url, get_db, initialize_database
from app.main import create_app
from app.security.csrf import csrf_token


def build_test_client(tmp_path: Path) -> TestClient:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'test.db'}")
    initialize_database(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


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
