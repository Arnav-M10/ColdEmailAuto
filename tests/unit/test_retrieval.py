from pathlib import Path

import pytest
from pypdf import PdfWriter
from sqlalchemy.orm import Session

from app.db.session import create_engine_for_url, initialize_database
from app.models.candidate import CandidateStatus
from app.models.publication import Publication
from app.services.candidates import create_candidate
from app.services.metadata import title_fingerprint
from app.services.retrieval import arxiv_pdf_url, retrieve_publication_pdf
from app.services.web_safety import FetchResult


class FakePDFFetcher:
    def __init__(self, result: FetchResult) -> None:
        self.result = result
        self.seen_url: str | None = None

    def fetch(self, url: str, *, expected: str = "pdf") -> FetchResult:
        self.seen_url = url
        assert expected == "pdf"
        return self.result


def make_pdf_bytes(path: Path) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with path.open("wb") as file:
        writer.write(file)
    return path.read_bytes()


def make_publication(*, arxiv_id: str | None = "2401.12345") -> Publication:
    return Publication(
        title="Cosmology With Public Survey Data",
        title_fingerprint=title_fingerprint("Cosmology With Public Survey Data"),
        year=2024,
        venue="Example Journal",
        doi=None,
        arxiv_id=arxiv_id,
        openalex_id=None,
        source="manual",
        open_access_url=None,
        pdf_url=None,
        author_count=2,
        metadata_json="{}",
    )


def test_arxiv_pdf_url_is_deterministic() -> None:
    assert arxiv_pdf_url("2401.12345v2") == "https://arxiv.org/pdf/2401.12345v2"


def test_retrieve_publication_pdf_stores_source_provenance(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'test.db'}")
    initialize_database(engine)
    pdf_bytes = make_pdf_bytes(tmp_path / "paper.pdf")

    with Session(engine) as session:
        candidate = create_candidate(
            session,
            full_name="Professor Jane Doe",
            title=None,
            institution=None,
            department=None,
            research_area=None,
            official_profile_url=None,
            notes=None,
        )
        publication = make_publication()
        session.add(publication)
        session.flush()
        fetcher = FakePDFFetcher(
            FetchResult(
                url="https://arxiv.org/pdf/2401.12345",
                final_url="https://arxiv.org/pdf/2401.12345",
                status_code=200,
                content_type="application/pdf",
                body=pdf_bytes,
                sha256="c" * 64,
                robots_allowed=True,
            ),
        )

        paper = retrieve_publication_pdf(
            session,
            candidate=candidate,
            publication=publication,
            fetcher=fetcher,
        )

    assert fetcher.seen_url == "https://arxiv.org/pdf/2401.12345"
    assert paper.publication_id == publication.id
    assert paper.source_url == "https://arxiv.org/pdf/2401.12345"
    assert paper.license_note == "arXiv public PDF."
    assert candidate.status == CandidateStatus.PAPERS_FOUND


def test_retrieve_publication_pdf_rejects_non_pdf_content(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'test.db'}")
    initialize_database(engine)

    with Session(engine) as session:
        candidate = create_candidate(
            session,
            full_name="Professor Jane Doe",
            title=None,
            institution=None,
            department=None,
            research_area=None,
            official_profile_url=None,
            notes=None,
        )
        publication = make_publication()
        session.add(publication)
        session.flush()
        fetcher = FakePDFFetcher(
            FetchResult(
                url="https://arxiv.org/pdf/2401.12345",
                final_url="https://arxiv.org/pdf/2401.12345",
                status_code=200,
                content_type="text/html",
                body=b"<html></html>",
                sha256="d" * 64,
                robots_allowed=True,
            ),
        )

        with pytest.raises(ValueError, match="PDF signature"):
            retrieve_publication_pdf(
                session,
                candidate=candidate,
                publication=publication,
                fetcher=fetcher,
            )
