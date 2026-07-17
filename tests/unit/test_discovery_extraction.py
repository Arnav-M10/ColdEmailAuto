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
    suggest_directory_page,
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

MIT_PHYSICS_HOMEPAGE_SNAPSHOT = """
<html>
  <body>
    <nav class="main-navigation">
      <a href="/about/">About</a>
      <a href="/physics-directory/">People Directory</a>
      <a href="/faculty/">Faculty Directory</a>
      <a href="/academic-programs/">Academic Programs</a>
      <a href="/research/">Research Areas</a>
      <a href="/news/">Latest Physics News</a>
    </nav>
    <main>
      <h1>This is the homepage h1</h1>
      <h2>Discoveries in Physics Research</h2>
      <ul class="homepage-program-links">
        <li><a href="/graduate-program/">Graduate Program</a></li>
        <li><a href="/undergraduate-program/">Undergraduate Program</a></li>
        <li><a href="/pappalardo-fellowships/">Pappalardo Fellowships in Physics</a></li>
      </ul>
      <section class="spotlight">
        <h2>Spotlight On</h2>
        <h3><a href="/news/george-benedek/">
          George B. Benedek, pioneer in experimental biophysics and physics, dies at 97
        </a></h3>
        <p>
          The Alfred H. Caspary Professor Emeritus of Physics and Biological Physics
          leaves behind a legacy of pioneering research and dedicated mentorship at MIT.
        </p>
      </section>
      <section>
        <h2>Our Research Areas</h2>
        <a href="/research/">Explore Our Research Areas</a>
      </section>
      <section>
        <h2>Our Faculty</h2>
        <p>We have five faculty who have won the Nobel Prize in Physics.</p>
        <a href="/faculty/">Learn about our faculty</a>
      </section>
      <section class="recent-news">
        <h2>Recent News</h2>
        <article>
          <h3><a href="/news/star-ate-planet/">
            This Star Just Ate a Planet, and It’s Not Done Yet
          </a></h3>
          <p>Categories: In The News, Graduate Students, Astrophysics Observation.</p>
        </article>
      </section>
    </main>
  </body>
</html>
"""


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


def test_mit_physics_homepage_resolves_faculty_directory_and_extracts_no_homepage_people() -> None:
    suggestion = suggest_directory_page(
        MIT_PHYSICS_HOMEPAGE_SNAPSHOT,
        source_url="https://physics.mit.edu/",
    )
    previews = extract_department_candidates(
        MIT_PHYSICS_HOMEPAGE_SNAPSHOT,
        source_url="https://physics.mit.edu/",
        institution="MIT",
        department="Physics",
    )

    assert suggestion.directory_url == "https://physics.mit.edu/faculty/"
    assert suggestion.confidence >= 0.8
    assert previews == []


def test_navigation_headings_and_news_headlines_are_rejected() -> None:
    html = """
    <nav>
      <a href="/graduate-program/">Graduate Program</a>
      <a href="/undergraduate-program/">Undergraduate Program</a>
      <a href="/research-areas/">Research Areas</a>
      <a href="/admissions/">Admissions</a>
      <a href="/events/">Events</a>
    </nav>
    <main>
      <h2>Research Areas</h2>
      <section class="news-list">
        <h3>Jane Doe Wins Major Physics Prize</h3>
        <p>Professor Jane Doe was mentioned in a news headline.</p>
      </section>
      <article class="post">
        <h3>John Smith, quantum researcher, gives colloquium</h3>
        <p>Associate Professor John Smith spoke at an event.</p>
      </article>
    </main>
    """

    previews = extract_department_candidates(
        html,
        source_url="https://physics.example.edu/",
        institution="Example",
        department="Physics",
    )

    assert previews == []


def test_extracted_person_requires_name_and_supporting_signal_with_source_element() -> None:
    html = """
    <main>
      <section class="faculty-card">
        <h3><a href="/faculty/anna-frebel/">Anna Frebel</a></h3>
        <p>Professor of Physics. Research uses computational astrophysics and data analysis.</p>
        <p>Email: frebel@example.edu</p>
      </section>
      <section>
        <h3>Graduate Program Undergraduate Program</h3>
        <p>Postdoctoral fellowship program resources and admissions news.</p>
      </section>
    </main>
    """

    previews = extract_department_candidates(
        html,
        source_url="https://physics.example.edu/faculty/",
        institution="Example",
        department="Physics",
    )

    assert [preview.full_name for preview in previews] == ["Anna Frebel"]
    assert previews[0].source_url == "https://physics.example.edu/faculty/"
    assert "<section.faculty-card>" in previews[0].source_element
    assert any("Source element:" in evidence for evidence in previews[0].evidence)


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
