from pathlib import Path

from sqlalchemy.orm import Session

from app.db.session import create_engine_for_url, initialize_database
from app.models.candidate import CandidateStatus
from app.services.candidate_screening import ScreeningContext, screen_candidate
from app.services.candidates import create_candidate


def build_session(tmp_path: Path) -> Session:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'test.db'}")
    initialize_database(engine)
    return Session(engine)


def context(
    *,
    full_name: str = "Ada Lovelace",
    title: str | None = "Assistant Professor of Physics",
    research_summary: str | None = (
        "Computational plasma simulations and magnetic field data analysis."
    ),
    role_category: str | None = "assistant_professor",
    duplicate_reasons: list[str] | None = None,
) -> ScreeningContext:
    return ScreeningContext(
        full_name=full_name,
        title=title,
        institution="Example University",
        department="Physics",
        research_summary=research_summary,
        active_topics=None,
        role_category=role_category,
        duplicate_reasons=duplicate_reasons or [],
    )


def test_emeritus_faculty_are_excluded_by_default(tmp_path: Path) -> None:
    with build_session(tmp_path) as session:
        result = screen_candidate(
            session,
            context(
                title="Professor of Physics, Emeritus",
                research_summary="Retired professor in theoretical astrophysics.",
                role_category="professor",
            ),
        )

    assert result.status == "EXCLUDED"
    assert any("emeritus" in reason.lower() for reason in result.exclusions)


def test_active_computational_assistant_professor_ranks_well(tmp_path: Path) -> None:
    with build_session(tmp_path) as session:
        result = screen_candidate(
            session,
            context(
                title="Assistant Professor of Physics",
                research_summary=(
                    "Computational solar wind plasma simulations, magnetic field time series, "
                    "uncertainty analysis, Python software, and student group projects."
                ),
                role_category="assistant_professor",
            ),
        )

    assert result.status == "INCLUDED"
    assert result.score >= 70
    assert any("Parker Solar Probe" in reason for reason in result.reasons)
    assert any("Assistant professor" in reason for reason in result.reasons)


def test_already_contacted_or_local_duplicate_is_excluded(tmp_path: Path) -> None:
    with build_session(tmp_path) as session:
        result = screen_candidate(
            session,
            context(duplicate_reasons=["Matching name and institution"]),
        )

    assert result.status == "EXCLUDED"
    assert any("local contact data" in reason for reason in result.exclusions)


def test_hardware_heavy_profile_without_computational_path_is_warned(tmp_path: Path) -> None:
    with build_session(tmp_path) as session:
        result = screen_candidate(
            session,
            context(
                title="Associate Professor of Physics",
                research_summary="Experimental detector hardware and laboratory instrumentation.",
                role_category="associate_professor",
            ),
        )

    assert result.status == "WARN"
    assert any("hardware-heavy" in warning for warning in result.warnings)


def test_same_group_as_contacted_person_is_warned(tmp_path: Path) -> None:
    with build_session(tmp_path) as session:
        contacted = create_candidate(
            session,
            full_name="Contacted Person",
            title="Professor",
            institution="Example University",
            department="Physics",
            research_area="Quantum Materials Group",
            official_profile_url=None,
            notes="Already contacted from Quantum Materials Group.",
        )
        contacted.status = CandidateStatus.SENT
        session.commit()

        result = screen_candidate(
            session,
            context(
                title="Assistant Professor of Physics",
                research_summary="Computational modeling in the Quantum Materials Group.",
                role_category="assistant_professor",
            ),
        )

    assert result.status == "WARN"
    assert any("same group" in warning.lower() for warning in result.warnings)
