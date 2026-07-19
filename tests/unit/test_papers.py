from pathlib import Path

import pytest
from pypdf import PdfWriter
from sqlalchemy.orm import Session

from app.db.session import create_engine_for_url, initialize_database
from app.services.candidates import create_candidate
from app.services.papers import store_manual_pdf, validate_pdf_bytes


def make_pdf_bytes(path: Path) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with path.open("wb") as file:
        writer.write(file)
    return path.read_bytes()


def test_pdf_bytes_must_have_pdf_signature() -> None:
    with pytest.raises(ValueError, match="PDF signature"):
        validate_pdf_bytes(b"<html></html>", 1024)


def test_manual_pdf_storage_ignores_unsafe_filename(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'test.db'}")
    initialize_database(engine)
    pdf_bytes = make_pdf_bytes(tmp_path / "source.pdf")

    with Session(engine) as session:
        candidate = create_candidate(
            session,
            full_name="Professor Jane Doe",
            title=None,
            institution="Example University",
            department=None,
            research_area=None,
            official_profile_url=None,
            notes=None,
        )
        paper = store_manual_pdf(
            session,
            candidate=candidate,
            original_filename="../../secret.pdf",
            content=pdf_bytes,
            project_root=tmp_path,
        )

    assert ".." not in paper.stored_path
    assert paper.stored_path.startswith("data/papers/professor-jane-doe/manual_")
    assert (tmp_path / paper.stored_path).exists()
