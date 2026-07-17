from pathlib import Path

import pytest
from pypdf import PdfWriter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import create_engine_for_url, initialize_database
from app.models.candidate import CandidateStatus
from app.models.paper import PaperFile
from app.models.publication import Publication
from app.services.candidates import create_candidate
from app.services.metadata import title_fingerprint
from app.services.retrieval import (
    arxiv_pdf_url,
    plan_publication_pdf_retrieval_candidates,
    retrieve_publication_pdf,
)
from app.services.web_safety import FetchResult


class FakePDFFetcher:
    def __init__(
        self,
        result: FetchResult | None = None,
        *,
        routes: dict[str, FetchResult] | None = None,
    ) -> None:
        self.result = result
        self.routes = routes or {}
        self.seen_url: str | None = None
        self.seen_urls: list[str] = []

    def fetch(self, url: str, *, expected: str = "pdf") -> FetchResult:
        self.seen_url = url
        self.seen_urls.append(url)
        assert expected == "pdf"
        if url in self.routes:
            return self.routes[url]
        if self.result is None:
            raise AssertionError(f"Unexpected URL: {url}")
        return self.result


def make_pdf_bytes(path: Path) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with path.open("wb") as file:
        writer.write(file)
    return path.read_bytes()


def make_publication(
    *,
    arxiv_id: str | None = "2401.12345",
    doi: str | None = None,
    pdf_url: str | None = None,
    open_access_url: str | None = None,
    metadata_json: str = "{}",
    source: str = "manual",
) -> Publication:
    return Publication(
        title="Cosmology With Public Survey Data",
        title_fingerprint=title_fingerprint("Cosmology With Public Survey Data"),
        year=2024,
        venue="Example Journal",
        doi=doi,
        arxiv_id=arxiv_id,
        openalex_id=None,
        source=source,
        open_access_url=open_access_url,
        pdf_url=pdf_url,
        author_count=2,
        metadata_json=metadata_json,
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


def test_retrieval_plans_prefer_arxiv_then_lawful_public_pdf() -> None:
    publication = make_publication(
        arxiv_id="2401.12345",
        pdf_url="https://iopscience.iop.org/article/10.1088/example/pdf",
    )

    plans = plan_publication_pdf_retrieval_candidates(publication)

    assert [plan.url for plan in plans] == [
        "https://arxiv.org/pdf/2401.12345",
        "https://iopscience.iop.org/article/10.1088/example/pdf",
    ]
    assert plans[1].license_note == "Approved public full-text host PDF."


def test_openalex_pdf_url_is_ranked_as_openalex_fallback() -> None:
    publication = make_publication(
        arxiv_id=None,
        pdf_url="https://iopscience.iop.org/article/10.1088/example/pdf",
        source="openalex",
    )

    plans = plan_publication_pdf_retrieval_candidates(publication)

    assert plans[0].rank == 5
    assert plans[0].source_type == "openalex_pdf_url"


def test_retrieve_publication_pdf_falls_back_to_next_lawful_source(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'test.db'}")
    initialize_database(engine)
    pdf_bytes = make_pdf_bytes(tmp_path / "paper.pdf")
    publication = make_publication(
        arxiv_id="2401.12345",
        pdf_url="https://iopscience.iop.org/article/10.1088/example/pdf",
    )

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
        session.add(publication)
        session.flush()
        fetcher = FakePDFFetcher(
            routes={
                "https://arxiv.org/pdf/2401.12345": FetchResult(
                    url="https://arxiv.org/pdf/2401.12345",
                    final_url="https://arxiv.org/pdf/2401.12345",
                    status_code=200,
                    content_type="text/html",
                    body=b"<html>withdrawn</html>",
                    sha256="e" * 64,
                    robots_allowed=True,
                ),
                "https://iopscience.iop.org/article/10.1088/example/pdf": FetchResult(
                    url="https://iopscience.iop.org/article/10.1088/example/pdf",
                    final_url="https://iopscience.iop.org/article/10.1088/example/pdf",
                    status_code=200,
                    content_type="application/pdf",
                    body=pdf_bytes,
                    sha256="f" * 64,
                    robots_allowed=True,
                ),
            },
        )

        paper = retrieve_publication_pdf(
            session,
            candidate=candidate,
            publication=publication,
            fetcher=fetcher,
        )

    assert fetcher.seen_urls == [
        "https://arxiv.org/pdf/2401.12345",
        "https://iopscience.iop.org/article/10.1088/example/pdf",
    ]
    assert paper.source_url == "https://iopscience.iop.org/article/10.1088/example/pdf"
    assert paper.license_note == "Approved public full-text host PDF."
    assert candidate.status == CandidateStatus.PAPERS_FOUND


def test_retrieve_publication_pdf_marks_no_full_text_when_no_plan(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'test.db'}")
    initialize_database(engine)
    publication = make_publication(arxiv_id=None, doi="10.1000/example")

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
        session.add(publication)
        session.flush()

        with pytest.raises(ValueError, match="10.1000/example"):
            retrieve_publication_pdf(session, candidate=candidate, publication=publication)

    assert candidate.status == CandidateStatus.NO_FULL_TEXT


def test_retrieve_publication_pdf_deduplicates_same_candidate_publication(
    tmp_path: Path,
) -> None:
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

        first = retrieve_publication_pdf(
            session,
            candidate=candidate,
            publication=publication,
            fetcher=fetcher,
        )
        second = retrieve_publication_pdf(
            session,
            candidate=candidate,
            publication=publication,
            fetcher=fetcher,
        )
        paper_count = len(list(session.scalars(select(PaperFile))))

    assert first.id == second.id
    assert paper_count == 1
