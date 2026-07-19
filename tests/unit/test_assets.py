from pathlib import Path
from typing import Any

from pypdf import PdfWriter

from app.services.assets import (
    PORTFOLIO_PATH,
    RESUME_PATH,
    build_asset_manifest,
    required_attachments_ready,
    store_private_pdf_upload,
    write_asset_manifest,
)


def write_minimal_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with path.open("wb") as file:
        writer.write(file)


def test_required_assets_validate_and_manifest_is_written(tmp_path: Path) -> None:
    write_minimal_pdf(tmp_path / RESUME_PATH)
    write_minimal_pdf(tmp_path / PORTFOLIO_PATH)

    manifest = build_asset_manifest(tmp_path)
    output = write_asset_manifest(manifest, tmp_path)

    assert manifest.all_required_valid
    assert output.exists()
    assert "sha256" in output.read_text(encoding="utf-8")
    assert required_attachments_ready(tmp_path)


def test_required_assets_block_when_missing(tmp_path: Path) -> None:
    manifest = build_asset_manifest(tmp_path)

    assert not manifest.all_required_valid
    assert not required_attachments_ready(tmp_path)


def test_private_resume_upload_stores_valid_pdf(tmp_path: Path) -> None:
    destination = tmp_path / "private" / "arnav_resume.pdf"
    source = tmp_path / "resume-source.pdf"
    write_minimal_pdf(source)
    content = source.read_bytes()

    result = store_private_pdf_upload(
        label="Resume",
        destination=destination,
        content=content,
        content_type="application/pdf",
        max_size_bytes=1024 * 1024,
    )

    assert destination.exists()
    assert destination.read_bytes() == content
    assert result.page_count == 1
    assert len(result.sha256) == 64


def test_private_portfolio_upload_requires_extractable_text(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    destination = tmp_path / "private" / "arnav_research_portfolio.pdf"
    content = b"%PDF-portfolio"

    class TextPage:
        def extract_text(self) -> str:
            return "compact binaries time-domain astrophysics"

    class TextReader:
        is_encrypted = False

        def __init__(self, _source: object) -> None:
            self.pages = [TextPage()]

    monkeypatch.setattr("app.services.assets.PdfReader", TextReader)

    result = store_private_pdf_upload(
        label="Research portfolio",
        destination=destination,
        content=content,
        content_type="application/pdf",
        max_size_bytes=1024 * 1024,
        require_text=True,
    )

    assert destination.exists()
    assert result.extracted_text == "compact binaries time-domain astrophysics"


def test_private_upload_rejects_invalid_pdf(tmp_path: Path) -> None:
    destination = tmp_path / "private" / "arnav_resume.pdf"

    try:
        store_private_pdf_upload(
            label="Resume",
            destination=destination,
            content=b"not a pdf",
            content_type="application/pdf",
            max_size_bytes=1024,
        )
    except ValueError as exc:
        assert "PDF signature" in str(exc)
    else:
        raise AssertionError("invalid PDF upload was accepted")

    assert not destination.exists()


def test_private_upload_rejects_oversized_pdf(tmp_path: Path) -> None:
    destination = tmp_path / "private" / "arnav_resume.pdf"

    try:
        store_private_pdf_upload(
            label="Resume",
            destination=destination,
            content=b"%PDF-" + (b"x" * 20),
            content_type="application/pdf",
            max_size_bytes=10,
        )
    except ValueError as exc:
        assert "size limit" in str(exc)
    else:
        raise AssertionError("oversized PDF upload was accepted")

    assert not destination.exists()
