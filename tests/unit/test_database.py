from sqlalchemy import select

from app.db.session import create_engine_for_url, initialize_database
from app.models.candidate import Candidate, CandidateStatus


def test_database_initializes_foundation_tables() -> None:
    engine = create_engine_for_url("sqlite:///:memory:")

    initialize_database(engine)

    with engine.begin() as connection:
        table_names = set(connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'",
        ).scalars())

    assert {"audit_events", "candidates", "jobs"}.issubset(table_names)


def test_candidate_default_status_is_discovered() -> None:
    engine = create_engine_for_url("sqlite:///:memory:")
    initialize_database(engine)

    from sqlalchemy.orm import Session

    with Session(engine) as session:
        candidate = Candidate(full_name="Dr. Ada Lovelace", institution="Example University")
        session.add(candidate)
        session.commit()

        stored = session.scalars(select(Candidate)).one()

    assert stored.status == CandidateStatus.DISCOVERED

