from collections.abc import Generator
from pathlib import Path

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.base import Base
from app.models import audit, candidate, draft, email_address, job, outreach, paper  # noqa: F401


def ensure_sqlite_parent_directory(database_url: str) -> None:
    if not database_url.startswith("sqlite:///"):
        return
    database_path = Path(database_url.removeprefix("sqlite:///"))
    if database_path == Path(":memory:"):
        return
    database_path.parent.mkdir(parents=True, exist_ok=True)


def create_engine_for_url(database_url: str) -> Engine:
    ensure_sqlite_parent_directory(database_url)
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args)


settings = get_settings()
engine = create_engine_for_url(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def initialize_database(target_engine: Engine = engine) -> None:
    Base.metadata.create_all(bind=target_engine)


def check_database(target_engine: Engine = engine) -> bool:
    with target_engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return True


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
