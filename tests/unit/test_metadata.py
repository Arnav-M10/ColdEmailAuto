import json
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
    approve_publication_for_retrieval,
    assert_publication_selected_for_retrieval,
    deduplicate_metadata,
    list_candidate_publication_reviews,
    list_candidate_publications,
    manual_publication_metadata,
    match_candidate_author,
    normalize_openalex_author_id,
    parse_openalex_work,
    rank_openalex_author_candidates,
    retrieve_recent_publications_for_candidate,
    score_openalex_author,
    score_publication_for_candidate,
    title_fingerprint,
    upsert_publication_with_authorship,
)


class FakeJSONClient(MetadataClientLike):
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def get_json(self, _url: str) -> dict[str, Any]:
        return self.payload


class FakeRouterJSONClient(MetadataClientLike):
    def __init__(self, routes: dict[str, dict[str, Any]]) -> None:
        self.routes = routes
        self.urls: list[str] = []

    def get_json(self, url: str) -> dict[str, Any]:
        self.urls.append(url)
        for key, payload in self.routes.items():
            if key in url:
                return payload
        raise AssertionError(f"Unexpected URL: {url}")


class FailingJSONClient(MetadataClientLike):
    def get_json(self, _url: str) -> dict[str, Any]:
        raise RuntimeError("not found")


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
                "author": {"id": "https://openalex.org/A1", "display_name": "Jane Doe"},
                "is_corresponding": True,
                "institutions": [{"display_name": "Example University"}],
            },
            {
                "author": {"id": "https://openalex.org/A2", "display_name": "Arun Patel"},
                "institutions": [],
            },
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


def test_openalex_same_name_author_disambiguation_prefers_institution() -> None:
    candidate = Candidate(
        full_name="Jane Doe",
        institution="Example University",
        research_area="magnetic field topology",
        status=CandidateStatus.DISCOVERED,
    )
    wrong = {
        "id": "https://openalex.org/Awrong",
        "display_name": "Jane Doe",
        "works_count": 40,
        "last_known_institutions": [{"display_name": "Other University"}],
    }
    right = {
        "id": "https://openalex.org/Aright",
        "display_name": "Jane Doe",
        "works_count": 12,
        "last_known_institutions": [{"display_name": "Example University"}],
    }

    ranked = sorted(
        [score_openalex_author(candidate, wrong), score_openalex_author(candidate, right)],
        key=lambda item: item.confidence,
        reverse=True,
    )

    assert ranked[0].openalex_id == "https://openalex.org/Aright"
    assert ranked[0].confidence >= 0.8
    assert any("affiliation" in reason.lower() for reason in ranked[0].reasons)


def test_kevin_burdge_openalex_ranking_prefers_mit_physics_affiliation() -> None:
    candidate = Candidate(
        full_name="Kevin Burdge",
        institution="MIT",
        department="Physics",
        research_area="time-domain astrophysics compact binaries stellar dynamics",
        official_profile_url="https://physics.mit.edu/faculty/kevin-burdge/",
        status=CandidateStatus.DISCOVERED,
    )
    wrong = score_openalex_author(
        candidate,
        {
            "id": "https://openalex.org/A999999",
            "display_name": "Kevin Burdge",
            "works_count": 30,
            "counts_by_year": [{"year": 2025, "works_count": 4}],
            "last_known_institutions": [{"display_name": "California Institute of Technology"}],
            "topics": [{"display_name": "Particle physics"}],
        },
    )
    right = score_openalex_author(
        candidate,
        {
            "id": "https://openalex.org/A123456",
            "display_name": "Kevin Burdge",
            "orcid": "https://orcid.org/0000-0002-0000-0000",
            "works_count": 18,
            "counts_by_year": [
                {"year": 2025, "works_count": 3},
                {"year": 2024, "works_count": 2},
                {"year": 2020, "works_count": 9},
            ],
            "last_known_institutions": [
                {"display_name": "Massachusetts Institute of Technology"},
            ],
            "affiliations": [
                {
                    "institution": {"display_name": "California Institute of Technology"},
                    "years": [2021, 2020],
                },
            ],
            "topics": [
                {"display_name": "Astrophysics"},
                {"display_name": "Compact binaries"},
                {"display_name": "Stellar dynamics"},
            ],
        },
    )

    ranked = rank_openalex_author_candidates(candidate, [wrong, right])

    assert ranked[0].openalex_id == "https://openalex.org/A123456"
    assert ranked[0].current_institutions == ["Massachusetts Institute of Technology"]
    assert ranked[0].previous_institutions == ["California Institute of Technology"]
    assert "Astrophysics" in ranked[0].topics
    assert ranked[0].recent_works_count == 5
    assert ranked[0].confidence > wrong.confidence


def test_openalex_author_id_normalization_requires_author_id() -> None:
    assert normalize_openalex_author_id("A123") == "https://openalex.org/A123"
    assert normalize_openalex_author_id("https://openalex.org/A123") == "https://openalex.org/A123"


def test_crossref_missing_doi_confirmation_returns_none() -> None:
    crossref = CrossrefClient(FailingJSONClient())

    assert crossref.work_by_doi("10.48550/arxiv.2604.08648") is None


def test_live_retrieval_can_use_manually_confirmed_openalex_author(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'test.db'}")
    initialize_database(engine)
    openalex_client = OpenAlexClient(
        FakeRouterJSONClient(
            {
                "/works?": {"results": [openalex_work()]},
            },
        ),
    )
    crossref_client = CrossrefClient(
        FakeRouterJSONClient(
            {
                "/works/10.1000%2Fexample": {
                    "message": {
                        "title": ["Topology of Magnetic Field Structures"],
                        "DOI": "10.1000/example",
                        "published-online": {"date-parts": [[2025, 1, 1]]},
                        "author": [{"given": "Jane", "family": "Doe"}],
                    },
                },
            },
        ),
    )

    with Session(engine) as session:
        candidate = create_candidate(
            session,
            full_name="Jane Doe",
            title="Assistant Professor",
            institution="Example University",
            department="Physics",
            research_area="magnetic field topology",
            official_profile_url=None,
            notes=None,
        )
        result = retrieve_recent_publications_for_candidate(
            session,
            candidate=candidate,
            openalex=openalex_client,
            crossref=crossref_client,
            confirmed_openalex_author_id="A1",
        )

    assert result.author.confidence == 1.0
    assert result.imported_count == 1


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


def test_live_publication_retrieval_confirms_doi_and_deduplicates(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'test.db'}")
    initialize_database(engine)
    openalex_client = OpenAlexClient(
        FakeRouterJSONClient(
            {
                "/authors?": {
                    "results": [
                        {
                            "id": "https://openalex.org/A1",
                            "display_name": "Jane Doe",
                            "works_count": 8,
                            "last_known_institutions": [
                                {"display_name": "Example University"},
                            ],
                        },
                    ],
                },
                "/works?": {"results": [openalex_work(), openalex_work()]},
            },
        ),
    )
    crossref_client = CrossrefClient(
        FakeRouterJSONClient(
            {
                "/works/10.1000%2Fexample": {
                    "message": {
                        "title": ["Topology of Magnetic Field Structures"],
                        "DOI": "10.1000/example",
                        "container-title": ["Confirmed Journal"],
                        "published-online": {"date-parts": [[2025, 1, 1]]},
                        "author": [{"given": "Jane", "family": "Doe"}],
                        "URL": "https://doi.org/10.1000/example",
                    },
                },
            },
        ),
    )

    with Session(engine) as session:
        candidate = create_candidate(
            session,
            full_name="Jane Doe",
            title="Assistant Professor",
            institution="Example University",
            department="Physics",
            research_area="magnetic field topology",
            official_profile_url=None,
            notes=None,
        )
        result = retrieve_recent_publications_for_candidate(
            session,
            candidate=candidate,
            openalex=openalex_client,
            crossref=crossref_client,
        )
        session.commit()

        publications = list(session.scalars(select(Publication)))
        authorships = list(session.scalars(select(Authorship)))

    assert result.imported_count == 1
    assert result.skipped_count == 1
    assert publications[0].venue == "Journal of Example Physics"
    assert "crossref_confirmation" in publications[0].metadata_json
    assert authorships[0].match_status == "MATCHED"


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


def test_confirmed_openalex_author_id_sets_authorship_without_name_match(
    tmp_path: Path,
) -> None:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'test.db'}")
    initialize_database(engine)
    metadata = PublicationMetadata(
        title="Compact Binary Discovery in Time-Domain Surveys",
        year=2025,
        venue="Example Astrophysics Journal",
        doi="10.1000/confirmed-author",
        arxiv_id="2502.12345",
        openalex_id="https://openalex.org/WKEVIN",
        source="openalex",
        open_access_url="https://arxiv.org/abs/2502.12345",
        pdf_url="https://arxiv.org/pdf/2502.12345",
        authors=["K. Burdge", "Collaborator"],
        author_institutions=["Massachusetts Institute of Technology"],
        raw={},
        author_openalex_ids=["https://openalex.org/A123456", "https://openalex.org/A999999"],
        corresponding_author_positions={1},
    )

    with Session(engine) as session:
        candidate = create_candidate(
            session,
            full_name="Kevin Burdge",
            title="Assistant Professor",
            institution="MIT",
            department="Physics",
            research_area="time-domain astrophysics compact binaries",
            official_profile_url="https://physics.mit.edu/faculty/kevin-burdge/",
            notes=None,
        )
        _publication, authorship = upsert_publication_with_authorship(
            session,
            candidate=candidate,
            metadata=metadata,
            confirmed_openalex_author_id="https://openalex.org/A123456",
        )
        session.commit()

        stored = session.get(Authorship, authorship.id)
        assert stored is not None
        warnings = json.loads(stored.warnings_json)

    assert stored.author_position == 1
    assert stored.author_count == 2
    assert stored.openalex_author_id == "https://openalex.org/A123456"
    assert stored.confirmed_author_present is True
    assert stored.corresponding_author is True
    assert stored.role == "corresponding_author"
    assert stored.match_status == "MATCHED"
    assert stored.identity_confidence == 0.95
    assert stored.score >= 80
    assert "Candidate name was not found in the author list." not in warnings


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


def test_publication_upsert_does_not_merge_unrelated_null_identifier_papers(
    tmp_path: Path,
) -> None:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'test.db'}")
    initialize_database(engine)

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
        for title in ["First No DOI Paper", "Second No DOI Paper"]:
            upsert_publication_with_authorship(
                session,
                candidate=candidate,
                metadata=PublicationMetadata(
                    title=title,
                    year=2025,
                    venue=None,
                    doi=None,
                    arxiv_id=None,
                    openalex_id=None,
                    source="openalex",
                    open_access_url=None,
                    pdf_url=None,
                    authors=["Jane Doe"],
                    author_institutions=["Example University"],
                    raw={},
                ),
            )
        session.commit()
        publications = list(session.scalars(select(Publication)))

    assert {publication.title for publication in publications} == {
        "First No DOI Paper",
        "Second No DOI Paper",
    }


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


def test_publication_selection_gate_requires_user_approval(tmp_path: Path) -> None:
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
        publication, _authorship = upsert_publication_with_authorship(
            session,
            candidate=candidate,
            metadata=PublicationMetadata(
                title="Cosmology With Public Survey Data",
                year=2024,
                venue="Example Journal",
                doi=None,
                arxiv_id="2401.12345",
                openalex_id=None,
                source="manual",
                open_access_url="https://arxiv.org/abs/2401.12345",
                pdf_url=None,
                authors=["Jane Doe", "Other Person"],
                author_institutions=["Example University"],
                raw={},
            ),
        )
        session.commit()

        try:
            assert_publication_selected_for_retrieval(
                session,
                candidate_id=candidate.id,
                publication_id=publication.id,
            )
        except ValueError as exc:
            assert "Approve this paper" in str(exc)
        else:  # pragma: no cover - defensive clarity
            raise AssertionError("Expected unapproved publication retrieval to be blocked.")

        approved = approve_publication_for_retrieval(
            session,
            candidate_id=candidate.id,
            publication_id=publication.id,
            notes="Strong fit with candidate research.",
        )
        reviews = list_candidate_publication_reviews(session, candidate.id)

        assert approved.selected_for_retrieval is True
        assert approved.selection_notes == "Strong fit with candidate research."
        assert reviews[0].full_text_label == "arXiv PDF available"
        assert reviews[0].full_text_available is True
        assert_publication_selected_for_retrieval(
            session,
            candidate_id=candidate.id,
            publication_id=publication.id,
        )


def create_unsaved_candidate() -> Candidate:
    return Candidate(
        full_name="Jane Doe",
        institution="Example University",
        research_area="cosmology data analysis",
        status=CandidateStatus.DISCOVERED,
    )
