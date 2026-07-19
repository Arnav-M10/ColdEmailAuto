from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from sqlalchemy.orm import Session, sessionmaker

from app.db.session import create_engine_for_url, initialize_database
from app.models.candidate import Candidate
from app.models.workflow import ResearchWorkflowRun
from app.routes import candidates as candidate_routes
from app.routes import publications as publication_routes
from app.security.csrf import csrf_token
from app.services.candidates import create_candidate


def test_confirm_author_post_resumes_exact_workflow_without_selection_redirect(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'test.db'}")
    initialize_database(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    resumed_workflow_ids: list[int] = []
    retrieved_author_ids: list[str] = []

    def fake_start_workflow(
        session: Session,
        *,
        candidate: Candidate,
        provider: Any | None = None,
        pdf_fetcher: Any | None = None,
        workflow: ResearchWorkflowRun | None = None,
    ) -> ResearchWorkflowRun:
        _ = (provider, pdf_fetcher, workflow)
        started = ResearchWorkflowRun(
            candidate_id=candidate.id,
            status="WAITING_FOR_AUTHOR_CONFIRMATION",
            current_stage="Finding publications",
        )
        session.add(started)
        session.flush()
        return started

    def fake_continue_workflow(
        session: Session,
        *,
        candidate: Candidate,
        provider: Any | None = None,
        pdf_fetcher: Any | None = None,
        workflow: ResearchWorkflowRun | None = None,
    ) -> ResearchWorkflowRun:
        _ = (session, candidate, provider, pdf_fetcher)
        assert workflow is not None
        resumed_workflow_ids.append(workflow.id)
        workflow.status = "READY_FOR_REVIEW"
        workflow.current_stage = "Ready for review"
        workflow.draft_id = 77
        return workflow

    def fake_retrieve_publications(*args: Any, **kwargs: Any) -> None:
        _ = args
        retrieved_author_ids.append(str(kwargs["confirmed_openalex_author_id"]))

    monkeypatch.setattr(candidate_routes, "run_research_workflow", fake_start_workflow)
    monkeypatch.setattr(publication_routes, "run_research_workflow", fake_continue_workflow)
    monkeypatch.setattr(
        publication_routes,
        "candidate_has_publications_for_openalex_author",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        publication_routes,
        "retrieve_recent_publications_for_candidate",
        fake_retrieve_publications,
    )

    with session_factory() as session:
        create_candidate(
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

        run_response = candidate_routes.candidate_run_research_workflow(
            1,
            csrf=csrf_token(),
            db=session,
        )
        confirmation_location = run_response.headers["location"]
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

        response = publication_routes.candidate_confirm_openalex_author(
            request=cast(Any, object()),
            candidate_id=1,
            csrf=csrf_token(),
            selected_openalex_author_id="https://openalex.org/A123456",
            resume_workflow=True,
            workflow_id=workflow_id,
            db=session,
        )

        assert confirmation_location.startswith(
            "/candidates/1/publications/openalex-author/confirm?resume_workflow=1",
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/drafts/77/manual-review"
        assert "/publications/select" not in response.headers["location"]
        assert resumed_workflow_ids == [workflow_id]
        assert retrieved_author_ids == ["https://openalex.org/A123456"]

        original = session.get(ResearchWorkflowRun, workflow_id)
        decoy_loaded = session.get(ResearchWorkflowRun, decoy_id)
        assert original is not None
        assert decoy_loaded is not None
        assert original.status == "READY_FOR_REVIEW"
        assert original.draft_id == 77
        assert decoy_loaded.status == "WAITING_FOR_AUTHOR_CONFIRMATION"
