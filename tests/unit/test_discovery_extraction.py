from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import create_engine_for_url, initialize_database
from app.models.candidate import Candidate
from app.models.discovery import DiscoveryCandidate, DiscoveryDecision
from app.services.discovery import (
    create_department_import,
    extract_department_candidates,
    get_discovery_candidate,
    save_discovery_candidate,
)
from app.services.web_safety import FetchResult

DEPARTMENT_FIXTURES = [
    """
    <article>
      <a href="/people/jane-doe">Jane Doe</a>
      <p>Assistant Professor. Computational astrophysics, plasma simulation, students.</p>
      <p>jane.doe@example.edu</p>
    </article>
    """,
    """
    <table>
      <tr>
        <td>Associate Professor Alan Smith</td>
        <td>Cosmology, numerical relativity, data analysis</td>
        <td><a href="https://astro.example.edu/alan">Homepage</a></td>
      </tr>
    </table>
    """,
    """
    <ul>
      <li>
        Dr. Priya Raman - Postdoctoral Researcher
        Research: topological data analysis and dynamical systems.
        Email: praman@example.edu
      </li>
    </ul>
    """,
    """
    <section>
      <h3>Marco Lee</h3>
      <div>Research Scientist</div>
      <div>Scientific computing, optimization, uncertainty quantification software.</div>
    </section>
    """,
    """
    <div class="person-card">
      <h2>Assistant Professor Elena Garcia</h2>
      <a href="/garcia">Lab page</a>
      <p>Time-domain astronomy, machine learning, undergraduate group projects.</p>
      <p>egarcia@example.edu</p>
    </div>
    """,
]


def test_department_extractor_handles_five_page_structures() -> None:
    names: list[str] = []
    for fixture in DEPARTMENT_FIXTURES:
        previews = extract_department_candidates(
            fixture,
            source_url="https://astro.example.edu/people",
            institution="Example University",
            department="Astronomy",
        )
        assert len(previews) == 1
        assert previews[0].score > 40
        assert previews[0].confidence >= 0.65
        names.append(previews[0].full_name)

    assert names == [
        "Jane Doe",
        "Alan Smith",
        "Priya Raman",
        "Marco Lee",
        "Elena Garcia",
    ]


def test_department_import_previews_are_not_candidates_until_saved(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'test.db'}")
    initialize_database(engine)
    previews = extract_department_candidates(
        DEPARTMENT_FIXTURES[0],
        source_url="https://astro.example.edu/people",
        institution="Example University",
        department="Astronomy",
    )
    fetch_result = FetchResult(
        url="https://astro.example.edu/people",
        final_url="https://astro.example.edu/people",
        status_code=200,
        content_type="text/html",
        body=DEPARTMENT_FIXTURES[0].encode("utf-8"),
        sha256="b" * 64,
        robots_allowed=True,
    )

    with Session(engine) as session:
        department_import = create_department_import(
            session,
            source_url=fetch_result.url,
            fetch_result=fetch_result,
            previews=previews,
            institution="Example University",
            department="Astronomy",
        )
        session.commit()
        assert session.scalar(select(Candidate)) is None
        preview = session.scalar(
            select(DiscoveryCandidate).where(DiscoveryCandidate.import_id == department_import.id),
        )
        assert preview is not None
        saved = save_discovery_candidate(session, preview)
        preview_id = preview.id
        saved_id = saved.id
        session.commit()

    with Session(engine) as session:
        saved_preview = get_discovery_candidate(session, preview_id)
        candidate = session.get(Candidate, saved_id)

    assert candidate is not None
    assert candidate.full_name == "Jane Doe"
    assert saved_preview is not None
    assert saved_preview.decision == DiscoveryDecision.SAVED
