import json
import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.candidate import Candidate
from app.models.outreach import OutreachEventType
from app.models.paper import PaperFile
from app.services.assets import calculate_sha256
from app.services.candidates import record_event

SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class ParsedPdf:
    page_count: int
    text: str
    warnings: list[str]
    extracted_characters: int
    blank_pages: int
    text_density: float


def slugify(value: str) -> str:
    slug = SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return slug or "unknown"


def validate_pdf_bytes(content: bytes, max_size_bytes: int) -> None:
    if len(content) > max_size_bytes:
        raise ValueError("PDF exceeds the configured file-size limit.")
    if not content.startswith(b"%PDF-"):
        raise ValueError("Uploaded file does not start with the PDF signature.")


def parse_pdf(path: Path) -> ParsedPdf:
    reader = PdfReader(path)
    if reader.is_encrypted:
        raise ValueError("Encrypted PDFs are not supported.")
    text_parts: list[str] = []
    blank_pages = 0
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if not text.strip():
            blank_pages += 1
        text_parts.append(f"\n\n--- Page {index} ---\n{text.strip()}")
    warnings = []
    if blank_pages:
        warnings.append(f"{blank_pages} page(s) had little or no extractable text.")
    extracted = len("".join(text_parts))
    return ParsedPdf(
        page_count=len(reader.pages),
        text="".join(text_parts).strip(),
        warnings=warnings,
        extracted_characters=extracted,
        blank_pages=blank_pages,
        text_density=extracted / max(len(reader.pages), 1),
    )


def store_manual_pdf(
    session: Session,
    *,
    candidate: Candidate,
    original_filename: str,
    content: bytes,
    publication_id: int | None = None,
    source_url: str | None = None,
    license_note: str | None = None,
    project_root: Path | None = None,
) -> PaperFile:
    settings = get_settings()
    root = project_root or settings.project_root
    storage_root = (
        root / "data" if project_root is not None else settings.resolved_runtime_data_dir
    )
    validate_pdf_bytes(content, settings.max_pdf_size_mb * 1024 * 1024)

    candidate_slug = slugify(candidate.full_name)
    temp_dir = storage_root / "papers" / candidate_slug
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / "upload.tmp"
    temp_path.write_bytes(content)

    sha256 = calculate_sha256(temp_path)
    existing = session.scalars(
        select(PaperFile).where(
            PaperFile.sha256 == sha256,
            PaperFile.candidate_id == candidate.id,
            PaperFile.publication_id == publication_id,
        ),
    ).first()
    if existing is not None:
        temp_path.unlink(missing_ok=True)
        return existing
    stored_path = temp_dir / f"manual_{sha256[:8]}.pdf"
    if not stored_path.exists():
        temp_path.replace(stored_path)
    else:
        temp_path.unlink(missing_ok=True)

    parsed = parse_pdf(stored_path)
    text_dir = storage_root / "cache" / "paper_text"
    text_dir.mkdir(parents=True, exist_ok=True)
    text_path = text_dir / f"{sha256}.txt"
    text_path.write_text(parsed.text, encoding="utf-8")

    paper_file = PaperFile(
        candidate_id=candidate.id,
        publication_id=publication_id,
        original_filename=Path(original_filename).name,
        stored_path=storage_path_reference(stored_path, root),
        sha256=sha256,
        size_bytes=len(content),
        page_count=parsed.page_count,
        parsed_text_path=storage_path_reference(text_path, root),
        source_url=source_url,
        license_note=license_note,
        text_quality_json=json.dumps(
            {
                "extracted_characters": parsed.extracted_characters,
                "blank_pages": parsed.blank_pages,
                "text_density": parsed.text_density,
                "warnings": parsed.warnings,
            },
        ),
    )
    session.add(paper_file)
    session.flush()
    record_event(
        session,
        candidate_id=candidate.id,
        event_type=OutreachEventType.PAPER_UPLOADED,
        notes=f"Manual PDF uploaded: {paper_file.original_filename}.",
    )
    return paper_file


def list_paper_files(session: Session) -> list[PaperFile]:
    return list(session.scalars(select(PaperFile).order_by(PaperFile.created_at.desc())))


def get_paper_file(session: Session, paper_file_id: int) -> PaperFile | None:
    return session.get(PaperFile, paper_file_id)


def read_parsed_text(paper_file: PaperFile) -> str:
    settings = get_settings()
    if paper_file.parsed_text_path is None:
        return ""
    path = resolve_storage_path(paper_file.parsed_text_path, settings.project_root)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def storage_path_reference(path: Path, project_root: Path) -> str:
    try:
        return str(path.relative_to(project_root))
    except ValueError:
        return str(path)


def resolve_storage_path(path_value: str, project_root: Path) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else project_root / path
