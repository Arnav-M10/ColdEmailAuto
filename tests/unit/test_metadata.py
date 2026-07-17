from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import create_engine_for_url, initialize_database
from app.models.candidate import Candidate, CandidateStatus
from app.models.publication import Authorship, Publication
from app.services.candidates import create_candidate
from app.services.metadata import (
    CrossrefClient,
    MetadataClientLike,
    OpenAlexClient,
    PublicationMetadata,
    deduplicate_metadata,
    list_candidate_publications,
    manual_publication_metadata,
    match_candidate_author,
    parse_openalex_work,
    score_publication_for_candidate,
    title_fingerprint,
    upsert_publication_with_authorship,
)


class FakeJSONClient(MetadataClientLike):
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def get_json(self, _url: str) -> dict[str, Any]:
        return self.payload


def openalex_work() -> dict[str, Any]:
    return {
        "id": "https://openalex.org/W123",
        "title": "Topology of Magnetic Field Structures",
        "publication_year": 2025,
        "doi": "https://doi.org/10.1000/example",
        "primary_location": {
            "landing_page_url": "https://journal.example.edu/paper",
            "pdf_url": "https://journal.example.edu/paper.pdf",
            "source": {"display_name": "Journal of Example Physics"},
        },
        "authorships": [
            {
                "author": {"display_name": "Jane Doe"},
                "institutions": [{"display_name": "Example University"}],
            },
            {"author": {"display_name": "Arun Patel"}, "institutions": []},
        ],
    }


def test_openalex_and_crossref_clients_normalize_metadata() -> None:
    openalex = OpenAlexClient(FakeJSONClient({"results": [openalex_work()]}))
    crossref = CrossrefClient(
        FakeJSONClient(
            {
                "message": {
                    "items": [
                        {
                            "title": ["Topology of Magnetic Field Structures"],
                            "DOI": "10.1000/example",
                            "container-title": ["Journal of Example Physics"],
                            "published-online": {"date-parts": [[2025, 1, 1]]},
                            "author": [{"given": "Jane", "family": "Doe"}],
                            "URL": "https://doi.org/10.1000/example",
                        },
                    ],
                },
            },
        ),
    )

    openalex_items = openalex.works_for_author("https://openalex.org/A1")
    crossref_items = crossref.works_by_query("Jane Doe topology")

    assert openalex_items[0].doi == "10.1000/example"
    assert openalex_items[0].pdf_url == "https://journal.example.edu/paper.pdf"
    assert crossref_items[0].authors == ["Jane Doe"]
    assert crossref_items[0].year == 2025


def test_publication_deduplication_prefers_identifier_keys() -> None:
    first = parse_openalex_work(openalex_work())
    duplicate = PublicationMetadata(
        title="Topology of Magnetic Field Structures",
        year=2025,
        venue=None,
        doi="10.1000/example",
        arxiv_id=None,
        openalex_id=None,
        source="crossref",
        open_access_url=None,
        pdf_url=None,
        authors=["Jane Doe"],
        author_institutions=[],
        raw={},
    )

    assert len(deduplicate_metadata([first, duplicate])) == 1
    assert title_fingerprint("Topology: of magnetic-field structures!") == (
        "topology of magnetic field structures"
    )


def test_author_identity_requires_review_for_mismatch_and_large_author_lists() -> None:
    metadata = PublicationMetadata(
        title="Consortium Map of the Sky",
        year=2024,
        venue=None,
        doi=None,
        arxiv_id=None,
        openalex_id=None,
        source="openalex",
        open_access_url=None,
        pdf_url=None,
        authors=["Other Person"] * 30,
        author_institutions=["Other University"],
        raw={},
    )
    candidate = create_unsaved_candidate()

    match = match_candidate_author(candidate, metadata)
    scored = score_publication_for_candidate(candidate, metadata, match)

    assert match.status == "REVIEW_REQUIRED"
    assert "Candidate name was not found in the author list." in match.warnings
    assert any("Large author list" in warning for warning in scored.warnings)


def test_publication_upsert_links_authorship_once(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'test.db'}")
    initialize_database(engine)
    metadata = parse_openalex_work(openalex_work())

    with Session(engine) as session:
        candidate = create_candidate(
            session,
            full_name="Jane Doe",
            title=None,
            institution="Example University",
            department=None,
            research_area="magnetic field topology",
            official_profile_url=None,
            notes=None,
        )
        first_publication, first_authorship = upsert_publication_with_authorship(
            session,
            candidate=candidate,
            metadata=metadata,
        )
        second_publication, second_authorship = upsert_publication_with_authorship(
            session,
            candidate=candidate,
            metadata=metadata,
        )
        first_publication_id = first_publication.id
        second_publication_id = second_publication.id
        first_authorship_id = first_authorship.id
        second_authorship_id = second_authorship.id
        session.commit()

    with Session(engine) as session:
        publications = list(session.scalars(select(Publication)))
        authorships = list(session.scalars(select(Authorship)))

    assert first_publication_id == second_publication_id
    assert first_authorship_id == second_authorship_id
    assert len(publications) == 1
    assert len(authorships) == 1
    assert authorships[0].match_status == "MATCHED"


def test_manual_scholar_publication_records_source_without_scraping(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'test.db'}")
    initialize_database(engine)

    with Session(engine) as session:
        candidate = create_candidate(
            session,
            full_name="Jane Doe",
            title=None,
            institution="Example University",
            department=None,
            research_area="cosmology data analysis",
            official_profile_url=None,
            notes=None,
        )
        metadata = manual_publication_metadata(
            title="Cosmology With Public Survey Data",
            year=2024,
            venue="Example Journal",
            doi="",
            arxiv_id="2401.12345",
            open_access_url="https://arxiv.org/abs/2401.12345",
            pdf_url="https://arxiv.org/pdf/2401.12345",
            authors_text="Jane Doe, Other Person",
            scholar_url="https://scholar.google.com/citations?user=abc",
        )
        publication, authorship = upsert_publication_with_authorship(
            session,
            candidate=candidate,
            metadata=metadata,
        )
        session.commit()
        publication_id = publication.id
        authorship_id = authorship.id

    with Session(engine) as session:
        rows = list_candidate_publications(session, candidate_id=1)
        loaded_publication = session.get(Publication, publication_id)
        loaded_authorship = session.get(Authorship, authorship_id)

    assert loaded_publication is not None
    assert loaded_publication.source == "manual_scholar"
    assert "scholar.google.com" in loaded_publication.metadata_json
    assert loaded_authorship is not None
    assert loaded_authorship.match_status == "REVIEW_REQUIRED"
    assert len(rows) == 1


def create_unsaved_candidate() -> Candidate:
    return Candidate(
        full_name="Jane Doe",
        institution="Example University",
        research_area="cosmology data analysis",
        status=CandidateStatus.DISCOVERED,
    )
