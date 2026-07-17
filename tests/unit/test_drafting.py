from pathlib import Path

from pypdf import PdfWriter
from sqlalchemy.orm import Session

from app.db.session import create_engine_for_url, initialize_database
from app.models.paper import EvidenceClassification
from app.services.analysis import create_manual_analysis, evidence_for_analysis
from app.services.candidates import add_email_address, create_candidate
from app.services.drafting import (
    contains_forbidden_phrase,
    generate_manual_draft,
    validate_draft_approval,
)
from app.services.papers import store_manual_pdf


def make_pdf_bytes(path: Path) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with path.open("wb") as file:
        writer.write(file)
    return path.read_bytes()


def test_forbidden_phrase_detection() -> None:
    assert contains_forbidden_phrase("I hope to leverage this robust method.") == [
        "leverage",
        "robust",
    ]


def test_draft_approval_requires_verified_email(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'test.db'}")
    initialize_database(engine)
    pdf_bytes = make_pdf_bytes(tmp_path / "paper.pdf")

    with Session(engine) as session:
        candidate = create_candidate(
            session,
            full_name="Professor Jane Doe",
            title=None,
            institution="Example",
            department=None,
            research_area=None,
            official_profile_url=None,
            notes=None,
        )
        paper = store_manual_pdf(
            session,
            candidate=candidate,
            original_filename="paper.pdf",
            content=pdf_bytes,
            project_root=tmp_path,
        )
        analysis = create_manual_analysis(
            session,
            candidate=candidate,
            paper_file=paper,
            title="magnetic field topology",
            research_question="How does the structure change?",
            methods="Persistent homology",
            results="The method identifies changes in structure.",
            connection_to_arnav="Parker Solar Probe magnetic-field analysis",
            claim="the use of persistent homology to track field structure",
            evidence_text="The paper uses persistent homology to compare field structure.",
            page_number=1,
            section_name="Methods",
            classification=EvidenceClassification.EXPLICIT,
            confidence=0.9,
        )
        evidence = evidence_for_analysis(session, analysis.id)[0]
        draft = generate_manual_draft(
            session,
            candidate=candidate,
            analysis=analysis,
            evidence=evidence,
        )
        errors = validate_draft_approval(session, draft=draft, project_root_override=tmp_path)

    assert "A verified official email is required." in errors


def test_draft_approval_passes_with_verified_email_and_assets(tmp_path: Path) -> None:
    from app.services.assets import PORTFOLIO_PATH, RESUME_PATH

    (tmp_path / RESUME_PATH).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / RESUME_PATH).write_bytes(make_pdf_bytes(tmp_path / "resume.pdf"))
    (tmp_path / PORTFOLIO_PATH).write_bytes(make_pdf_bytes(tmp_path / "portfolio.pdf"))
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'test.db'}")
    initialize_database(engine)
    pdf_bytes = make_pdf_bytes(tmp_path / "paper.pdf")

    with Session(engine) as session:
        candidate = create_candidate(
            session,
            full_name="Professor Jane Doe",
            title=None,
            institution="Example",
            department=None,
            research_area=None,
            official_profile_url=None,
            notes=None,
        )
        add_email_address(
            session,
            candidate_id=candidate.id,
            email="jane@example.edu",
            source_url="https://example.edu/jane",
            source_type="official_university_page",
            confidence="HIGH",
            verification_status="VERIFIED",
        )
        paper = store_manual_pdf(
            session,
            candidate=candidate,
            original_filename="paper.pdf",
            content=pdf_bytes,
            project_root=tmp_path,
        )
        analysis = create_manual_analysis(
            session,
            candidate=candidate,
            paper_file=paper,
            title="magnetic field topology",
            research_question="How does the structure change?",
            methods="Persistent homology",
            results="The method identifies changes in structure.",
            connection_to_arnav="Parker Solar Probe magnetic-field analysis",
            claim="the use of persistent homology to track field structure",
            evidence_text="The paper uses persistent homology to compare field structure.",
            page_number=1,
            section_name="Methods",
            classification=EvidenceClassification.EXPLICIT,
            confidence=0.9,
        )
        evidence = evidence_for_analysis(session, analysis.id)[0]
        draft = generate_manual_draft(
            session,
            candidate=candidate,
            analysis=analysis,
            evidence=evidence,
        )
        errors = validate_draft_approval(session, draft=draft, project_root_override=tmp_path)

    assert errors == []
