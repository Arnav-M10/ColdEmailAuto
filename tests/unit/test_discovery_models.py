from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import create_engine_for_url, initialize_database
from app.models.discovery import (
    DepartmentImport,
    DepartmentImportStatus,
    DiscoveryCandidate,
    DiscoveryDecision,
)


def test_discovery_review_tables_store_preview_without_candidate_persistence(
    tmp_path: Path,
) -> None:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'test.db'}")
    initialize_database(engine)

    with Session(engine) as session:
        department_import = DepartmentImport(
            source_url="https://astro.example.edu/people",
            final_url="https://astro.example.edu/people",
            source_title="Astrophysics Faculty",
            status=DepartmentImportStatus.REVIEW_READY,
            robots_allowed=True,
            page_sha256="a" * 64,
        )
        session.add(department_import)
        session.flush()
        session.add(
            DiscoveryCandidate(
                import_id=department_import.id,
                full_name="Professor Jane Doe",
                title="Assistant Professor",
                institution="Example University",
                department="Astronomy",
                role_category="assistant_professor",
                research_summary="Computational astrophysics",
                active_topics="magnetohydrodynamics",
                remote_feasibility="High: computational work",
                mentoring_likelihood="Medium",
                research_overlap="Parker Solar Probe magnetic-field analysis",
                confidence=0.82,
                score=78,
                official_email="jane@example.edu",
                official_homepage="https://astro.example.edu/jane",
                source_url="https://astro.example.edu/people",
                evidence_json='["Assistant Professor listing"]',
                warnings_json="[]",
                decision=DiscoveryDecision.REVIEW_PENDING,
            ),
        )
        session.commit()

    with Session(engine) as session:
        previews = list(session.scalars(select(DiscoveryCandidate)))

    assert len(previews) == 1
    assert previews[0].saved_candidate_id is None
