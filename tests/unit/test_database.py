from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import normalize_sqlite_database_url
from app.db.session import create_engine_for_url, initialize_database
from app.models.candidate import Candidate, CandidateStatus


def test_database_initializes_foundation_tables() -> None:
    engine = create_engine_for_url("sqlite:///:memory:")

    initialize_database(engine)

    with engine.begin() as connection:
        table_names = set(connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'",
        ).scalars())

    assert {
        "audit_events",
        "candidates",
        "jobs",
        "email_addresses",
        "paper_files",
        "paper_analyses",
        "evidence_items",
        "drafts",
        "outreach_events",
        "follow_up_tasks",
    }.issubset(table_names)


def test_railway_relative_data_sqlite_url_is_normalized_to_absolute_volume() -> None:
    normalized = normalize_sqlite_database_url(
        "sqlite:///data/outreach.db",
        railway_runtime=True,
    )

    assert normalized == "sqlite:////data/outreach.db"


def test_absolute_sqlite_database_records_persist_after_engine_recreate(tmp_path: Path) -> None:
    database_path = tmp_path / "data" / "outreach.db"
    database_url = f"sqlite:///{database_path}"
    first_engine = create_engine_for_url(database_url)
    initialize_database(first_engine)
    with Session(first_engine) as session:
        session.add(Candidate(full_name="Persistent Candidate", institution="MIT"))
        session.commit()
    first_engine.dispose()

    second_engine = create_engine_for_url(database_url)
    initialize_database(second_engine)
    with Session(second_engine) as session:
        stored = session.scalars(select(Candidate)).one()
    second_engine.dispose()

    assert database_path.exists()
    assert stored.full_name == "Persistent Candidate"


def test_candidate_default_status_is_discovered() -> None:
    engine = create_engine_for_url("sqlite:///:memory:")
    initialize_database(engine)

    with Session(engine) as session:
        candidate = Candidate(full_name="Dr. Ada Lovelace", institution="Example University")
        session.add(candidate)
        session.commit()

        stored = session.scalars(select(Candidate)).one()

    assert stored.status == CandidateStatus.DISCOVERED


def test_database_initializes_candidate_openalex_author_storage() -> None:
    engine = create_engine_for_url("sqlite:///:memory:")
    initialize_database(engine)

    with engine.begin() as connection:
        columns = {
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(candidates)").fetchall()
        }

    assert "openalex_author_id" in columns


def test_database_initializes_authorship_openalex_author_storage() -> None:
    engine = create_engine_for_url("sqlite:///:memory:")
    initialize_database(engine)

    with engine.begin() as connection:
        columns = {
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(authorships)").fetchall()
        }

    assert "openalex_author_id" in columns
    assert "confirmed_author_present" in columns
    assert "corresponding_author" in columns
    assert "score_details_json" in columns


def test_database_initializes_publication_ranking_storage() -> None:
    engine = create_engine_for_url("sqlite:///:memory:")
    initialize_database(engine)

    with engine.begin() as connection:
        columns = {
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(publications)").fetchall()
        }

    assert "citation_count" in columns
    assert "work_type" in columns
