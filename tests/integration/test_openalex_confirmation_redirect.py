import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy.orm import sessionmaker

from app.db.session import create_engine_for_url, initialize_database
from app.models.candidate import Candidate
from app.models.paper import EvidenceClassification, PaperFile
from app.models.publication import Authorship, Publication
from app.models.workflow import ResearchWorkflowRun
from app.services.ai_providers import EvidenceClaim, MockProvider, PaperAnalysisOutput
from app.services.candidates import add_email_address, create_candidate
from app.services.research_workflow import run_research_workflow
from app.services.workflow_navigation import (
    automatic_workflow_destination,
    resumed_workflow_destination,
)


def test_run_research_workflow_with_confirmed_author_reaches_draft_review_without_selection(
    tmp_path: Path, monkeypatch: Any
) -> None:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'app.db'}")
    initialize_database(engine)
    session_factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    confirmed_author_id = "https://openalex.org/A1234567890"

    parsed_text_path = tmp_path / "paper-text.txt"
    parsed_text_path.write_text(
        "The paper reports compact binary discoveries from time-domain surveys with "
        "clear links to gravitational-wave follow-up.",
        encoding="utf-8",
    )

    def fake_pdf_fetcher(*args: Any, **kwargs: Any) -> PaperFile:
        session = args[0]
        candidate = kwargs["candidate"]
        publication = kwargs["publication"]
        paper = PaperFile(
            candidate_id=candidate.id,
            publication_id=publication.id,
            original_filename="auto-workflow.pdf",
            stored_path=str(tmp_path / "paper.pdf"),
            source_url="https://arxiv.org/pdf/2502.12345",
            sha256="a" * 64,
            size_bytes=512,
            page_count=1,
            parsed_text_path=str(parsed_text_path),
            license_note="arXiv public PDF.",
            text_quality_json="{}",
        )
        session.add(paper)
        session.flush()
        return paper

    provider = MockProvider(
        PaperAnalysisOutput(
            title="Compact Binary Discoveries in Time-Domain Surveys",
            research_question="How can time-domain surveys identify compact binaries?",
            motivation="The paper connects compact binaries with survey follow-up.",
            methods="The paper uses time-domain survey analysis.",
            results="The authors identify compact-binary candidates for follow-up.",
            limitations="Follow-up observations remain limited.",
            overclaim_risks="Do not imply independent verification.",
            connection_to_arnav=(
                "This connects to scientific Python and compact-object follow-up."
            ),
            confidence=0.82,
            evidence=[
                EvidenceClaim(
                    claim="The paper studies compact binaries using time-domain surveys.",
                    evidence_text="compact binary discoveries from time-domain surveys",
                    page_number=1,
                    section_name="Extracted text",
                    classification=EvidenceClassification.EXPLICIT,
                    confidence=0.9,
                )
            ],
        ),
    )
    available_portfolio = SimpleNamespace(
        available=True,
        text="compact binaries time-domain surveys gravitational-wave follow-up",
        status="AVAILABLE",
        reason=None,
        source_path="assets/arnav_research_portfolio.pdf",
        sha256="b" * 64,
        cache_path="data/cache/portfolio_text/test.txt",
    )

    def fake_get_ai_provider(*args: Any, **kwargs: Any) -> MockProvider:
        _ = (args, kwargs)
        return provider

    monkeypatch.setattr(
        "app.services.research_workflow.retrieve_publication_pdf", fake_pdf_fetcher
    )
    monkeypatch.setattr(
        "app.services.research_workflow.get_ai_provider", fake_get_ai_provider
    )
    monkeypatch.setattr(
        "app.services.research_workflow.load_research_portfolio_text_status",
        lambda: available_portfolio,
    )
    monkeypatch.setattr(
        "app.services.research_workflow.required_attachments_ready",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "app.services.drafting.required_attachments_ready",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "app.services.research_workflow.manual_review_context",
        lambda *args, **kwargs: SimpleNamespace(
            approval_errors=[],
            sentence_checks=[],
        ),
    )

    with session_factory() as session:
        candidate = create_candidate(
            session,
            full_name="Kevin Burdge",
            title="Assistant Professor of Physics",
            institution="MIT",
            department="Physics",
            research_area="compact binaries time-domain astronomy",
            official_profile_url="https://physics.mit.edu/faculty/kevin-burdge/",
            notes=None,
        )
        candidate.openalex_author_id = confirmed_author_id
        add_email_address(
            session,
            candidate_id=candidate.id,
            email="kburdge@mit.edu",
            source_url="https://physics.mit.edu/faculty/kevin-burdge/",
            source_type="faculty profile",
            confidence="high",
            verification_status="verified",
        )
        publication = Publication(
            openalex_id="https://openalex.org/W1234567890",
            doi="https://doi.org/10.48550/arXiv.2502.12345",
            arxiv_id="2502.12345",
            title="Compact binary discoveries in time-domain surveys",
            title_fingerprint="compact-binary-discoveries-in-time-domain-surveys",
            year=2025,
            venue="arXiv",
            source="openalex",
            open_access_url="https://arxiv.org/abs/2502.12345",
            pdf_url="https://arxiv.org/pdf/2502.12345",
            citation_count=18,
            author_count=3,
            work_type="article",
            metadata_json=json.dumps(
                {"topics": ["compact binaries", "time-domain astronomy"]}
            ),
        )
        session.add(publication)
        session.flush()
        session.add(
            Authorship(
                candidate_id=candidate.id,
                publication_id=publication.id,
                openalex_author_id=confirmed_author_id,
                author_position=1,
                author_count=3,
                confirmed_author_present=True,
                corresponding_author=True,
                role="corresponding_author",
                match_status="MATCHED",
                identity_confidence=0.99,
                score=94.0,
                score_details_json=json.dumps(
                    {
                        "components": {
                            "portfolio_similarity": 32.0,
                            "author_role": 20.0,
                            "author_count": 12.0,
                            "recency": 11.0,
                            "pdf_availability": 8.0,
                            "citations": 1.0,
                        },
                        "reasons": [
                            "Strong portfolio match for compact binary work.",
                            "Confirmed OpenAlex author appears as first author.",
                        ],
                    }
                ),
                warnings_json="[]",
            )
        )
        session.commit()

    with session_factory() as session:
        loaded_candidate = session.get(Candidate, 1)
        assert loaded_candidate is not None
        workflow = run_research_workflow(session, candidate=loaded_candidate)
        session.commit()

        location = automatic_workflow_destination(1, workflow)
        assert location == "/drafts/1/manual-review"
        assert "/publications/select" not in location
        assert "publication_selection.html" not in location

        loaded_workflow = session.get(ResearchWorkflowRun, workflow.id)
        assert loaded_workflow is not None
        assert loaded_workflow.status == "READY_FOR_REVIEW"
        assert loaded_workflow.selected_publication_id == 1
        assert loaded_workflow.paper_file_id is not None
        assert loaded_workflow.analysis_id is not None
        assert loaded_workflow.draft_id == 1


def test_confirm_author_post_resumes_exact_workflow_without_selection_redirect(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'test.db'}")
    initialize_database(engine)
    session_factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    confirmed_author_id = "https://openalex.org/A123456"
    parsed_text_path = tmp_path / "confirmed-paper-text.txt"
    parsed_text_path.write_text(
        "The paper studies compact binaries with time-domain survey data.",
        encoding="utf-8",
    )
    provider = MockProvider(
        PaperAnalysisOutput(
            title="Compact Binaries from Survey Data",
            research_question="How can survey data identify compact binaries?",
            motivation="The paper studies compact-object follow-up.",
            methods="The paper uses time-domain survey data.",
            results="The authors report compact-binary candidates.",
            limitations="The extracted text notes limited follow-up.",
            overclaim_risks="Do not claim independent validation.",
            connection_to_arnav="This connects to computational astronomy interests.",
            confidence=0.84,
            evidence=[
                EvidenceClaim(
                    claim="The paper studies compact binaries with survey data.",
                    evidence_text="compact binaries with time-domain survey data",
                    page_number=1,
                    section_name="Extracted text",
                    classification=EvidenceClassification.EXPLICIT,
                    confidence=0.91,
                )
            ],
        ),
    )
    available_portfolio = SimpleNamespace(
        available=True,
        text="compact binaries time-domain surveys gravitational-wave follow-up",
        status="AVAILABLE",
        reason=None,
        source_path="assets/arnav_research_portfolio.pdf",
        sha256="b" * 64,
        cache_path="data/cache/portfolio_text/test.txt",
    )

    def fake_get_ai_provider(*args: Any, **kwargs: Any) -> MockProvider:
        _ = (args, kwargs)
        return provider

    def fake_pdf_fetcher(*args: Any, **kwargs: Any) -> PaperFile:
        session = args[0]
        candidate = kwargs["candidate"]
        publication = kwargs["publication"]
        paper = PaperFile(
            candidate_id=candidate.id,
            publication_id=publication.id,
            original_filename="confirmed-workflow.pdf",
            stored_path=str(tmp_path / "confirmed-paper.pdf"),
            source_url="https://arxiv.org/pdf/2502.23456",
            sha256="c" * 64,
            size_bytes=512,
            page_count=1,
            parsed_text_path=str(parsed_text_path),
            license_note="arXiv public PDF.",
            text_quality_json="{}",
        )
        session.add(paper)
        session.flush()
        return paper

    monkeypatch.setattr(
        "app.services.research_workflow.retrieve_publication_pdf", fake_pdf_fetcher
    )
    monkeypatch.setattr(
        "app.services.research_workflow.get_ai_provider", fake_get_ai_provider
    )
    monkeypatch.setattr(
        "app.services.research_workflow.load_research_portfolio_text_status",
        lambda: available_portfolio,
    )
    monkeypatch.setattr(
        "app.services.research_workflow.required_attachments_ready",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "app.services.drafting.required_attachments_ready",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "app.services.research_workflow.manual_review_context",
        lambda *args, **kwargs: SimpleNamespace(
            approval_errors=[],
            sentence_checks=[],
        ),
    )

    with session_factory() as session:
        candidate = create_candidate(
            session,
            full_name="Kevin Burdge",
            title="Assistant Professor",
            institution="MIT",
            department="Physics",
            research_area="compact binaries time-domain astrophysics",
            official_profile_url="https://physics.mit.edu/faculty/kevin-burdge/",
            notes=None,
        )
        session.commit()

        waiting_workflow = run_research_workflow(session, candidate=candidate)
        session.commit()
        confirmation_location = automatic_workflow_destination(1, waiting_workflow)
        workflow_id = int(confirmation_location.rsplit("workflow_id=", maxsplit=1)[1])

        later_timestamp = datetime.now(UTC) + timedelta(minutes=1)
        decoy = ResearchWorkflowRun(
            candidate_id=1,
            status="WAITING_FOR_AUTHOR_CONFIRMATION",
            current_stage="Finding publications",
            created_at=later_timestamp,
            updated_at=later_timestamp,
        )
        session.add(decoy)
        session.commit()
        decoy_id = decoy.id

        candidate.openalex_author_id = confirmed_author_id
        add_email_address(
            session,
            candidate_id=candidate.id,
            email="kburdge@mit.edu",
            source_url="https://physics.mit.edu/faculty/kevin-burdge/",
            source_type="faculty profile",
            confidence="high",
            verification_status="verified",
        )
        publication = Publication(
            openalex_id="https://openalex.org/WCONFIRMED",
            doi="https://doi.org/10.48550/arXiv.2502.23456",
            arxiv_id="2502.23456",
            title="Compact binaries from survey data",
            title_fingerprint="compact-binaries-from-survey-data",
            year=2025,
            venue="arXiv",
            source="openalex",
            open_access_url="https://arxiv.org/abs/2502.23456",
            pdf_url="https://arxiv.org/pdf/2502.23456",
            citation_count=11,
            author_count=4,
            work_type="article",
            metadata_json=json.dumps({"topics": ["compact binaries"]}),
        )
        session.add(publication)
        session.flush()
        session.add(
            Authorship(
                candidate_id=candidate.id,
                publication_id=publication.id,
                openalex_author_id=confirmed_author_id,
                author_position=1,
                author_count=4,
                confirmed_author_present=True,
                corresponding_author=True,
                role="corresponding_author",
                identity_confidence=0.98,
                match_status="MATCHED",
                score=93.0,
                connection_summary="compact binaries",
                warnings_json="[]",
                score_details_json=json.dumps(
                    {
                        "components": {"portfolio_similarity": 31.0},
                        "reasons": [
                            "Strong portfolio match for compact binary work.",
                            "Confirmed OpenAlex author appears as first author.",
                        ],
                    }
                ),
            )
        )
        session.flush()
        original = session.get(ResearchWorkflowRun, workflow_id)
        assert original is not None
        resumed = run_research_workflow(session, candidate=candidate, workflow=original)
        session.commit()
        location = resumed_workflow_destination(candidate.id, resumed)

        assert confirmation_location.startswith(
            "/candidates/1/publications/openalex-author/confirm?resume_workflow=1",
        )
        assert location == "/drafts/1/manual-review"
        assert "/publications/select" not in location
        assert "publication_selection.html" not in location
        assert resumed.id == workflow_id

        original = session.get(ResearchWorkflowRun, workflow_id)
        decoy_loaded = session.get(ResearchWorkflowRun, decoy_id)
        assert original is not None
        assert decoy_loaded is not None
        assert original.status == "READY_FOR_REVIEW"
        assert original.draft_id == 1
        assert decoy_loaded.status == "WAITING_FOR_AUTHOR_CONFIRMATION"
