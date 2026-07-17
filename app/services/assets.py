import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel
from pypdf import PdfReader

from app.config import get_settings

RESUME_PATH = Path("assets/arnav_resume.pdf")
PORTFOLIO_PATH = Path("assets/arnav_research_portfolio.pdf")
MANIFEST_PATH = Path("data/local_asset_manifest.json")


class AssetStatus(BaseModel):
    label: str
    relative_path: str
    exists: bool
    is_pdf: bool
    page_count: int | None
    size_bytes: int | None
    sha256: str | None
    error: str | None = None

    @property
    def valid(self) -> bool:
        return self.exists and self.is_pdf and self.page_count is not None and self.page_count > 0


class AssetManifest(BaseModel):
    generated_at: datetime
    assets: list[AssetStatus]

    @property
    def all_required_valid(self) -> bool:
        return all(asset.valid for asset in self.assets)


def required_asset_paths() -> dict[str, Path]:
    return {
        "Resume": RESUME_PATH,
        "Research portfolio": PORTFOLIO_PATH,
    }


def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_pdf(path: Path) -> tuple[bool, int | None, str | None]:
    try:
        with path.open("rb") as file:
            header = file.read(5)
        if header != b"%PDF-":
            return False, None, "File does not start with the PDF signature."

        reader = PdfReader(path)
        if reader.is_encrypted:
            return False, None, "Encrypted PDFs are not supported for required assets."
        page_count = len(reader.pages)
        if page_count < 1:
            return False, None, "PDF has no pages."
        return True, page_count, None
    except Exception as exc:
        return False, None, f"PDF validation failed: {exc.__class__.__name__}"


def inspect_asset(project_root: Path, label: str, relative_path: Path) -> AssetStatus:
    path = project_root / relative_path
    if not path.exists():
        return AssetStatus(
            label=label,
            relative_path=str(relative_path),
            exists=False,
            is_pdf=False,
            page_count=None,
            size_bytes=None,
            sha256=None,
            error="File is missing.",
        )

    is_pdf, page_count, error = validate_pdf(path)
    return AssetStatus(
        label=label,
        relative_path=str(relative_path),
        exists=True,
        is_pdf=is_pdf,
        page_count=page_count,
        size_bytes=path.stat().st_size,
        sha256=calculate_sha256(path) if is_pdf else None,
        error=error,
    )


def build_asset_manifest(project_root: Path | None = None) -> AssetManifest:
    root = project_root or get_settings().project_root
    return AssetManifest(
        generated_at=datetime.now(UTC),
        assets=[
            inspect_asset(root, label, relative_path)
            for label, relative_path in required_asset_paths().items()
        ],
    )


def write_asset_manifest(
    manifest: AssetManifest,
    project_root: Path | None = None,
    manifest_path: Path = MANIFEST_PATH,
) -> Path:
    root = project_root or get_settings().project_root
    destination = root / manifest_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return destination


def refresh_asset_manifest(project_root: Path | None = None) -> AssetManifest:
    manifest = build_asset_manifest(project_root)
    write_asset_manifest(manifest, project_root)
    return manifest


def load_asset_manifest(project_root: Path | None = None) -> AssetManifest | None:
    root = project_root or get_settings().project_root
    path = root / MANIFEST_PATH
    if not path.exists():
        return None
    return AssetManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))


def required_attachments_ready(project_root: Path | None = None) -> bool:
    return build_asset_manifest(project_root).all_required_valid

