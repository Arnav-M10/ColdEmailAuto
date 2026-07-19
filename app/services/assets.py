import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
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
    configured_path: str = ""
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


@dataclass(frozen=True)
class UploadValidationResult:
    page_count: int
    sha256: str
    size_bytes: int
    extracted_text: str | None = None


def required_asset_paths() -> dict[str, Path]:
    settings = get_settings()
    return {
        "Resume": settings.resolved_resume_pdf_path,
        "Research portfolio": settings.resolved_research_portfolio_pdf_path,
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


def validate_pdf_upload(
    *,
    content: bytes,
    content_type: str | None,
    max_size_bytes: int,
    require_text: bool = False,
) -> UploadValidationResult:
    if not content:
        raise ValueError("Uploaded file is empty.")
    if len(content) > max_size_bytes:
        raise ValueError("Uploaded PDF exceeds the configured size limit.")
    if content[:5] != b"%PDF-":
        raise ValueError("Uploaded file does not start with the PDF signature.")
    allowed_content_types = {"application/pdf", "application/x-pdf"}
    if content_type not in allowed_content_types:
        raise ValueError("Uploaded file must use the application/pdf MIME type.")
    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs are not supported.")
        page_count = len(reader.pages)
        if page_count < 1:
            raise ValueError("Uploaded PDF has no pages.")
        extracted_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if require_text and not extracted_text.strip():
            raise ValueError("Research portfolio PDF text extraction returned empty text.")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"PDF validation failed: {exc.__class__.__name__}.") from exc
    return UploadValidationResult(
        page_count=page_count,
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        extracted_text=extracted_text,
    )


def store_private_pdf_upload(
    *,
    label: str,
    destination: Path,
    content: bytes,
    content_type: str | None,
    max_size_bytes: int,
    require_text: bool = False,
) -> UploadValidationResult:
    result = validate_pdf_upload(
        content=content,
        content_type=content_type,
        max_size_bytes=max_size_bytes,
        require_text=require_text,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.with_name(f".{destination.name}.tmp")
    try:
        temporary_path.write_bytes(content)
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, destination)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    if require_text:
        from app.services.metadata import clear_research_portfolio_text_cache

        clear_research_portfolio_text_cache()
    refresh_asset_manifest()
    return result


def display_path(path: Path, project_root: Path) -> str:
    try:
        return str(path.relative_to(project_root))
    except ValueError:
        return str(path)


def inspect_asset(project_root: Path, label: str, path: Path) -> AssetStatus:
    if not path.is_absolute():
        path = project_root / path
    rendered_path = display_path(path, project_root)
    if not path.exists():
        return AssetStatus(
            label=label,
            relative_path=rendered_path,
            configured_path=str(path),
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
        relative_path=rendered_path,
        configured_path=str(path),
        exists=True,
        is_pdf=is_pdf,
        page_count=page_count,
        size_bytes=path.stat().st_size,
        sha256=calculate_sha256(path) if is_pdf else None,
        error=error,
    )


def build_asset_manifest(project_root: Path | None = None) -> AssetManifest:
    root = project_root or get_settings().project_root
    asset_paths = (
        {
            "Resume": root / RESUME_PATH,
            "Research portfolio": root / PORTFOLIO_PATH,
        }
        if project_root is not None
        else required_asset_paths()
    )
    return AssetManifest(
        generated_at=datetime.now(UTC),
        assets=[
            inspect_asset(root, label, path)
            for label, path in asset_paths.items()
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
