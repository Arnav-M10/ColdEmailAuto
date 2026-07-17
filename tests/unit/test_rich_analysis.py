from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import create_engine_for_url, initialize_database
from app.models.candidate import CandidateStatus
from app.models.paper import PaperFile
from app.services.analysis import (
    create_structured_analysis_from_text,
    evidence_for_analysis,
    extract_structured_notes,
)
from app.services.candidates import create_candidate


def test_extract_structured_notes_keeps_claims_grounded() -> None:
    notes = extract_structured_notes(
        "We investigate magnetic structures. "
        "Our method uses numerical simulation and a Python package. "
        "We use survey observations as the dataset. "
        "A limitation is uncertain calibration. "
        "Future work will compare more events.",
    )

    assert "numerical simulation" in notes["methods"].lower()
    assert "survey observations" in notes["datasets"].lower()
    assert "uncertain calibration" in notes["limitations"].lower()
    assert "data analysis" in notes["contribution_areas"]


def test_structured_analysis_creates_evidence_item(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'test.db'}")
    initialize_database(engine)
    settings = get_settings()
    text_dir = settings.project_root / "data" / "cache" / "paper_text"
    text_dir.mkdir(parents=True, exist_ok=True)
    text_path = text_dir / "test-rich-analysis.txt"
    text_path.write_text(
        "--- Page 1 ---\n"
        "We investigate magnetic structures. "
        "Our method uses numerical simulation. "
        "We find coherent field patterns. "
        "A limitation is uncertain calibration.",
        encoding="utf-8",
    )

    with Session(engine) as session:
        candidate = create_candidate(
            session,
            full_name="Professor Jane Doe",
            title=None,
            institution=None,
            department=None,
            research_area=None,
            official_profile_url=None,
            notes=None,
        )
        paper = PaperFile(
            candidate_id=candidate.id,
            publication_id=None,
            original_filename="paper.pdf",
            stored_path="papers/jane/paper.pdf",
            sha256="e" * 64,
            size_bytes=100,
            page_count=1,
            parsed_text_path=str(text_path.relative_to(settings.project_root)),
            source_url=None,
            license_note=None,
            text_quality_json="{}",
        )
        session.add(paper)
        session.flush()
        analysis = create_structured_analysis_from_text(
            session,
            candidate=candidate,
            paper_file=paper,
            title="Magnetic structures",
            connection_to_arnav="Parker Solar Probe magnetic-field analysis",
        )
        evidence = evidence_for_analysis(session, analysis.id)

    assert analysis.computational_methods is not None
    assert analysis.overclaim_risks is not None
    assert evidence
    assert evidence[0].evidence_text
    assert candidate.status == CandidateStatus.PAPER_ANALYZED
