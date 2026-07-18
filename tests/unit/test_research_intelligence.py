from pathlib import Path
from typing import cast

from sqlalchemy.orm import Session

from app.db.session import create_engine_for_url, initialize_database
from app.models.publication import Authorship, Publication
from app.services.candidates import create_candidate
from app.services.metadata import title_fingerprint
from app.services.research_intelligence import (
    build_or_reuse_researcher_profile,
    email_usefulness_for_publication,
    profile_view,
)


def test_researcher_profile_synthesizes_clusters_and_portfolio_connections(
    tmp_path: Path,
) -> None:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'test.db'}")
    initialize_database(engine)
    with Session(engine) as session:
        candidate = create_candidate(
            session,
            full_name="Professor Jane Doe",
            title=None,
            institution="Example University",
            department="Physics",
            research_area="time-domain astrophysics",
            official_profile_url=None,
            notes=None,
        )
        publication = Publication(
            title="Magnetic Field Time Series in Solar Wind Surveys",
            title_fingerprint=title_fingerprint("Magnetic Field Time Series in Solar Wind Surveys"),
            year=2025,
            venue="Example Journal",
            doi="10.1000/intelligence",
            arxiv_id="2501.10000",
            openalex_id="https://openalex.org/WINTELLIGENCE",
            source="openalex",
            open_access_url="https://arxiv.org/abs/2501.10000",
            pdf_url="https://arxiv.org/pdf/2501.10000",
            author_count=2,
            citation_count=4,
            work_type="article",
            metadata_json=(
                '{"abstract":"persistent homology and bootstrap analysis of magnetic-field '
                'time series in the solar wind","authorships":[{"author":{"display_name":'
                '"Collaborator A"}}]}'
            ),
        )
        session.add(publication)
        session.flush()
        authorship = Authorship(
            candidate_id=candidate.id,
            publication_id=publication.id,
            author_position=1,
            author_count=2,
            confirmed_author_present=True,
            role="first_author",
            identity_confidence=0.9,
            match_status="MATCHED",
            score=80,
            warnings_json="[]",
            score_details_json='{"components":{"portfolio_similarity":30},"reasons":[]}',
        )
        session.add(authorship)
        session.flush()

        profile = build_or_reuse_researcher_profile(session, candidate=candidate)
        cached = build_or_reuse_researcher_profile(session, candidate=candidate)
        view = profile_view(profile)
        usefulness = email_usefulness_for_publication(
            publication=publication,
            authorship=authorship,
            profile=profile,
        )

        assert cached.id == profile.id
        assert view is not None
        assert view.clusters
        areas = [cast(str, item["area"]) for item in view.portfolio_connections]
        assert any("Parker Solar Probe" in area for area in areas)
        assert usefulness.score > 40
        assert usefulness.represents_broader_theme is True
