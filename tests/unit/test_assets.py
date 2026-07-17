from pathlib import Path

from pypdf import PdfWriter

from app.services.assets import (
    PORTFOLIO_PATH,
    RESUME_PATH,
    build_asset_manifest,
    required_attachments_ready,
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
