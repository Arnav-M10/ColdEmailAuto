from collections.abc import Generator
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings, normalize_sqlite_database_url
from app.db.base import Base
from app.models import (  # noqa: F401
    audit,
    candidate,
    discovery,
    draft,
    email_address,
    intelligence,
    job,
    outreach,
    paper,
    publication,
    workflow,
)

SQLITE_BUSY_TIMEOUT_MS = 30_000
SQLITE_LOCK_MESSAGES = (
    "database is locked",
    "database table is locked",
    "database schema is locked",
)


def ensure_sqlite_parent_directory(database_url: str) -> None:
    database_url = normalize_sqlite_database_url(database_url)
    if not database_url.startswith("sqlite:///"):
        return
    database_path = Path(database_url.removeprefix("sqlite:///"))
    if database_path == Path(":memory:"):
        return
    database_path.parent.mkdir(parents=True, exist_ok=True)


def create_engine_for_url(database_url: str) -> Engine:
    database_url = normalize_sqlite_database_url(database_url)
    ensure_sqlite_parent_directory(database_url)
    sqlite = database_url.startswith("sqlite")
    connect_args: dict[str, Any] = {}
    if sqlite:
        connect_args = {
            "check_same_thread": False,
            "timeout": SQLITE_BUSY_TIMEOUT_MS / 1000,
        }
    created_engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)
    if sqlite:
        configure_sqlite_pragmas(created_engine, enable_wal=is_sqlite_file_database(database_url))
    return created_engine


def is_sqlite_file_database(database_url: str) -> bool:
    if not database_url.startswith("sqlite:///"):
        return False
    database_path = database_url.removeprefix("sqlite:///")
    return database_path not in {":memory:", ""}


def configure_sqlite_pragmas(target_engine: Engine, *, enable_wal: bool) -> None:
    @event.listens_for(target_engine, "connect")
    def set_sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
            cursor.execute("PRAGMA foreign_keys=ON")
            if enable_wal:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()


def is_sqlite_lock_error(exc: BaseException) -> bool:
    if not isinstance(exc, OperationalError):
        return False
    message = str(exc.orig).lower() if getattr(exc, "orig", None) else str(exc).lower()
    return any(lock_message in message for lock_message in SQLITE_LOCK_MESSAGES)


settings = get_settings()
engine = create_engine_for_url(settings.effective_database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def initialize_database(target_engine: Engine = engine) -> None:
    Base.metadata.create_all(bind=target_engine)
    _ensure_candidate_openalex_author_column(target_engine)
    _ensure_draft_ai_review_column(target_engine)
    _ensure_publication_ranking_columns(target_engine)
    _ensure_authorship_openalex_author_column(target_engine)
    _ensure_research_workflow_columns(target_engine)


def _ensure_candidate_openalex_author_column(target_engine: Engine) -> None:
    if target_engine.dialect.name != "sqlite":
        return
    with target_engine.begin() as connection:
        columns = {
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(candidates)").fetchall()
        }
        if "openalex_author_id" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE candidates ADD COLUMN openalex_author_id VARCHAR(200)",
            )


def _ensure_draft_ai_review_column(target_engine: Engine) -> None:
    if target_engine.dialect.name != "sqlite":
        return
    with target_engine.begin() as connection:
        columns = {
            row[1] for row in connection.exec_driver_sql("PRAGMA table_info(drafts)").fetchall()
        }
        if "ai_review_json" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE drafts ADD COLUMN ai_review_json TEXT DEFAULT '{}' NOT NULL",
            )


def _ensure_publication_ranking_columns(target_engine: Engine) -> None:
    if target_engine.dialect.name != "sqlite":
        return
    with target_engine.begin() as connection:
        columns = {
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(publications)").fetchall()
        }
        if "citation_count" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE publications ADD COLUMN citation_count INTEGER DEFAULT 0 NOT NULL",
            )
        if "work_type" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE publications ADD COLUMN work_type VARCHAR(80)",
            )


def _ensure_authorship_openalex_author_column(target_engine: Engine) -> None:
    if target_engine.dialect.name != "sqlite":
        return
    with target_engine.begin() as connection:
        columns = {
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(authorships)").fetchall()
        }
        if "openalex_author_id" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE authorships ADD COLUMN openalex_author_id VARCHAR(200)",
            )
        if "confirmed_author_present" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE authorships "
                "ADD COLUMN confirmed_author_present BOOLEAN DEFAULT 0 NOT NULL",
            )
        if "corresponding_author" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE authorships "
                "ADD COLUMN corresponding_author BOOLEAN DEFAULT 0 NOT NULL",
            )
        if "score_details_json" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE authorships ADD COLUMN score_details_json TEXT DEFAULT '{}' NOT NULL",
            )


def _ensure_research_workflow_columns(target_engine: Engine) -> None:
    if target_engine.dialect.name != "sqlite":
        return
    with target_engine.begin() as connection:
        tables = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'",
            ).fetchall()
        }
        if "research_workflow_runs" not in tables:
            return
        columns = {
            row[1]
            for row in connection.exec_driver_sql(
                "PRAGMA table_info(research_workflow_runs)",
            ).fetchall()
        }
        if "researcher_profile_id" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE research_workflow_runs ADD COLUMN researcher_profile_id INTEGER",
            )
        if "summary_json" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE research_workflow_runs "
                "ADD COLUMN summary_json TEXT DEFAULT '{}' NOT NULL",
            )
        if "claim_check_json" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE research_workflow_runs "
                "ADD COLUMN claim_check_json TEXT DEFAULT '[]' NOT NULL",
            )
        if "ai_request_count" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE research_workflow_runs "
                "ADD COLUMN ai_request_count INTEGER DEFAULT 0 NOT NULL",
            )


def check_database(target_engine: Engine = engine) -> bool:
    with target_engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return True


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
