from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import create_engine_for_url, get_db, initialize_database
from app.main import create_app
from app.models.paper import PaperFile
from app.models.publication import Authorship, Publication
from app.security.csrf import csrf_token
from app.services.ai_providers import (
    EvidenceClaim,
    EvidenceClassification,
    MockProvider,
    PaperAnalysisOutput,
)
from app.services.candidates import add_email_address, create_candidate
from app.services.metadata import title_fingerprint


def build_test_context(tmp_path: Path) -> tuple[TestClient, Any]:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'test.db'}")
    initialize_database(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), session_factory


def analysis_provider() -> MockProvider:
    return MockProvider(
        PaperAnalysisOutput(
            title="Magnetic Structures in Time-Domain Surveys",
            research_question="How do surveys identify magnetic structures?",
            motivation="The paper studies time-domain survey signals.",
            methods="The paper uses numerical checks and survey analysis.",
            results="The paper reports a compact analysis workflow.",
            overclaim_risks="Do not imply independent verification.",
            connection_to_arnav="scientific Python and magnetic-field analysis",
            confidence=0.84,
            evidence=[
                EvidenceClaim(
                    claim="the paper uses numerical checks and survey analysis",
                    evidence_text="The paper uses numerical checks and survey analysis.",
                    page_number=1,
                    section_name="Extracted text",
                    classification=EvidenceClassification.EXPLICIT,
                    confidence=0.9,
                ),
            ],
        ),
    )


def test_start_outreach_reaches_finished_copy_ready_draft(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    client, session_factory = build_test_context(tmp_path)
    with session_factory() as session:
        candidate = create_candidate(
            session,
            full_name="Professor Jane Doe",
            title="Assistant Professor",
            institution="Example University",
            department="Physics",
            research_area="magnetic fields computational astrophysics",
            official_profile_url="https://example.edu/jane",
            notes=None,
        )
        candidate.openalex_author_id = "https://openalex.org/A1"
        publication = Publication(
            title="Magnetic Structures in Time-Domain Surveys",
            title_fingerprint=title_fingerprint("Magnetic Structures in Time-Domain Surveys"),
            year=2025,
            venue="Example Journal",
            doi="10.1000/outreach-agent",
            arxiv_id="2504.33333",
            openalex_id="https://openalex.org/WAGENT",
            source="openalex",
            open_access_url="https://arxiv.org/abs/2504.33333",
            pdf_url="https://arxiv.org/pdf/2504.33333",
            author_count=2,
            citation_count=9,
            work_type="article",
            metadata_json="{}",
        )
        session.add(publication)
        session.flush()
        session.add(
            Authorship(
                candidate_id=candidate.id,
                publication_id=publication.id,
                author_position=1,
                author_count=2,
                openalex_author_id="https://openalex.org/A1",
                confirmed_author_present=True,
                corresponding_author=False,
                role="first_author",
                identity_confidence=0.95,
                match_status="MATCHED",
                score=90.0,
                connection_summary="magnetic fields",
                warnings_json="[]",
                score_details_json=(
                    '{"components":{"portfolio_similarity":30.0},'
                    '"reasons":["Portfolio similarity matched: magnetic fields.",'
                    '"Confirmed author is first author.","Author count: 2.",'
                    '"Recent publication from 2025."]}'
                ),
            ),
        )
        add_email_address(
            session,
            candidate_id=candidate.id,
            email="jane@example.edu",
            source_url="https://example.edu/jane",
            source_type="official_faculty_profile",
            confidence="HIGH",
            verification_status="VERIFIED",
        )
        session.commit()

    text_dir = tmp_path / "data" / "cache" / "paper_text"
    text_dir.mkdir(parents=True, exist_ok=True)
    text_path = text_dir / "outreach-agent.txt"
    text_path.write_text(
        "--- Page 1 --- The paper uses numerical checks and survey analysis.",
        encoding="utf-8",
    )
    paper_settings = SimpleNamespace(
        max_pdf_size_mb=25,
        project_root=tmp_path,
        resolved_runtime_data_dir=tmp_path / "data",
    )

    def fake_retrieve_publication_pdf(*args: Any, **kwargs: Any) -> PaperFile:
        session = args[0]
        candidate = kwargs["candidate"]
        publication = kwargs["publication"]
        paper = PaperFile(
            candidate_id=candidate.id,
            publication_id=publication.id,
            original_filename="outreach-agent.pdf",
            stored_path="papers/test/outreach-agent.pdf",
            sha256="9" * 64,
            size_bytes=512,
            page_count=1,
            parsed_text_path=str(text_path.relative_to(tmp_path)),
            source_url="https://arxiv.org/pdf/2504.33333",
            license_note="arXiv public PDF.",
            text_quality_json="{}",
        )
        session.add(paper)
        session.flush()
        return paper

    provider = analysis_provider()
    monkeypatch.setattr("app.services.outreach_agent.get_ai_provider", lambda: provider)
    monkeypatch.setattr(
        "app.services.research_workflow.retrieve_publication_pdf",
        fake_retrieve_publication_pdf,
    )
    monkeypatch.setattr(
        "app.services.research_workflow.load_research_portfolio_text_status",
        lambda: SimpleNamespace(
            available=True,
            text="magnetic fields computational astrophysics survey analysis",
            status="AVAILABLE",
            reason=None,
        ),
    )
    monkeypatch.setattr("app.services.research_workflow.required_attachments_ready", lambda: True)
    monkeypatch.setattr("app.services.drafting.required_attachments_ready", lambda *_: True)
    monkeypatch.setattr("app.services.papers.get_settings", lambda: paper_settings)

    response = client.post(
        "/outreach/start",
        data={"csrf": csrf_token()},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert str(response.url).endswith("/outreach/drafts/1")
    assert "Finished Draft" in response.text
    assert "AI review passed" in response.text
    assert "Copy complete email" in response.text
    assert "jane@example.edu" in response.text
    assert "Select Publication" not in response.text
    assert "Run Research Workflow" not in response.text
    assert provider.calls == 1
    assert provider.review_calls == 1

    with session_factory() as session:
        from app.models.draft import Draft

        draft = session.get(Draft, 1)
        assert draft is not None
        assert '"overall_passed":true' in draft.ai_review_json.replace(" ", "")
