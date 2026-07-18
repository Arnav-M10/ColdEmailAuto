from collections.abc import Sequence
from typing import cast

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.models.candidate import Candidate
from app.models.publication import Publication
from app.security.csrf import csrf_token, validate_csrf_token
from app.services.candidates import get_candidate, list_candidates
from app.services.metadata import (
    OpenAlexAuthorCandidate,
    approve_publication_for_retrieval,
    assert_publication_selected_for_retrieval,
    candidate_has_publications_for_openalex_author,
    list_candidate_publication_reviews,
    list_candidate_publications,
    list_openalex_author_candidates_for_candidate,
    list_publications,
    manual_publication_metadata,
    normalize_openalex_author_id,
    retrieve_recent_publications_for_candidate,
    upsert_publication_with_authorship,
)
from app.services.research_workflow import run_research_workflow
from app.services.retrieval import retrieve_publication_pdf

router = APIRouter()
MIN_CONFIDENT_AUTHOR_SCORE = 0.75
PUBLICATION_SELECTION_PATH = "/candidates/{candidate_id}/publications/select"
PUBLICATION_SORT_OPTIONS = {
    "best": "Best outreach match",
    "newest": "Newest",
    "citations": "Highest citation count",
    "fewest_authors": "Fewest authors",
}


def render(request: Request, template_name: str, context: dict[str, object]) -> HTMLResponse:
    templates = request.app.state.templates
    base_context = request.app.state.base_context()
    base_context.update(context)
    return cast(HTMLResponse, templates.TemplateResponse(request, template_name, base_context))


def render_author_selection(
    request: Request,
    *,
    candidate: Candidate,
    author_candidates: Sequence[OpenAlexAuthorCandidate],
    error_message: str | None = None,
) -> HTMLResponse:
    preselected_author_id = ""
    if author_candidates:
        first = author_candidates[0]
        preselected_author_id = getattr(first, "openalex_id", "")
    return render(
        request,
        "publication_author_selection.html",
        {
            "active_page": "publications",
            "page_title": "Confirm OpenAlex Author",
            "candidate": candidate,
            "author_candidates": author_candidates,
            "preselected_author_id": preselected_author_id,
            "error_message": error_message,
            "csrf_token": csrf_token(),
        },
    )


def publication_selection_url(candidate_id: int) -> str:
    return PUBLICATION_SELECTION_PATH.format(candidate_id=candidate_id)


def workflow_or_selection_redirect(db: Session, candidate: Candidate) -> RedirectResponse:
    if not get_settings().auto_select_paper:
        return RedirectResponse(publication_selection_url(candidate.id), status_code=303)
    workflow = run_research_workflow(db, candidate=candidate)
    if workflow.draft_id is not None:
        return RedirectResponse(f"/drafts/{workflow.draft_id}/manual-review", status_code=303)
    if workflow.paper_file_id is not None:
        return RedirectResponse(f"/papers/{workflow.paper_file_id}", status_code=303)
    if workflow.selected_publication_id is not None:
        return RedirectResponse(publication_selection_url(candidate.id), status_code=303)
    return RedirectResponse(f"/candidates/{candidate.id}", status_code=303)


@router.get("/publications", response_class=HTMLResponse)
def publications_index(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    candidates = list_candidates(db)
    candidate_rows = [
        {
            "candidate": candidate,
            "publication_count": len(list_candidate_publications(db, candidate.id)),
        }
        for candidate in candidates
    ]
    return render(
        request,
        "publications.html",
        {
            "active_page": "publications",
            "page_title": "Publications",
            "candidate_rows": candidate_rows,
            "publications": list_publications(db),
            "csrf_token": csrf_token(),
        },
    )


@router.get("/candidates/{candidate_id}/publications/select", response_class=HTMLResponse)
def candidate_publication_selection(
    request: Request,
    candidate_id: int,
    sort: str = Query("best"),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    candidate = get_candidate(db, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404)
    selected_sort = sort if sort in PUBLICATION_SORT_OPTIONS else "best"
    return render(
        request,
        "publication_selection.html",
        {
            "active_page": "publications",
            "page_title": "Select Publication",
            "candidate": candidate,
            "publication_reviews": list_candidate_publication_reviews(
                db,
                candidate_id,
                sort=selected_sort,
            ),
            "sort_options": PUBLICATION_SORT_OPTIONS,
            "selected_sort": selected_sort,
            "csrf_token": csrf_token(),
        },
    )


@router.post("/candidates/{candidate_id}/publications/manual")
def candidate_add_manual_publication(
    candidate_id: int,
    csrf: str = Form(...),
    title: str = Form(...),
    year: int | None = Form(None),
    venue: str = Form(""),
    doi: str = Form(""),
    arxiv_id: str = Form(""),
    open_access_url: str = Form(""),
    pdf_url: str = Form(""),
    authors: str = Form(...),
    scholar_url: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_csrf_token(csrf)
    candidate = get_candidate(db, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404)
    if not title.strip():
        raise HTTPException(status_code=400, detail="Publication title is required.")
    metadata = manual_publication_metadata(
        title=title,
        year=year,
        venue=venue,
        doi=doi,
        arxiv_id=arxiv_id,
        open_access_url=open_access_url,
        pdf_url=pdf_url,
        authors_text=authors,
        scholar_url=scholar_url,
    )
    upsert_publication_with_authorship(db, candidate=candidate, metadata=metadata)
    db.commit()
    return RedirectResponse(publication_selection_url(candidate_id), status_code=303)


@router.post("/candidates/{candidate_id}/publications/retrieve-live")
def candidate_retrieve_live_publications(
    request: Request,
    candidate_id: int,
    csrf: str = Form(...),
    openalex_author_id: str = Form(""),
    db: Session = Depends(get_db),
) -> Response:
    validate_csrf_token(csrf)
    candidate = get_candidate(db, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404)
    confirmed_author_id = openalex_author_id.strip()
    if confirmed_author_id:
        try:
            candidate.openalex_author_id = normalize_openalex_author_id(confirmed_author_id)
            if not candidate_has_publications_for_openalex_author(
                db,
                candidate_id=candidate_id,
                openalex_author_id=candidate.openalex_author_id,
            ):
                retrieve_recent_publications_for_candidate(
                    db,
                    candidate=candidate,
                    confirmed_openalex_author_id=candidate.openalex_author_id,
                )
        except ValueError as exc:
            return render_author_selection(
                request,
                candidate=candidate,
                author_candidates=[],
                error_message=str(exc),
            )
        response = workflow_or_selection_redirect(db, candidate)
        db.commit()
        return response
    if candidate.openalex_author_id and candidate_has_publications_for_openalex_author(
        db,
        candidate_id=candidate_id,
        openalex_author_id=candidate.openalex_author_id,
    ):
        response = workflow_or_selection_redirect(db, candidate)
        db.commit()
        return response
    if not candidate.openalex_author_id:
        try:
            author_candidates = list_openalex_author_candidates_for_candidate(candidate)
        except Exception as exc:
            return render_author_selection(
                request,
                candidate=candidate,
                author_candidates=[],
                error_message=f"OpenAlex author lookup failed: {exc}",
            )
        needs_confirmation = (
            len(author_candidates) != 1
            or author_candidates[0].confidence < MIN_CONFIDENT_AUTHOR_SCORE
        )
        if needs_confirmation:
            return render_author_selection(
                request,
                candidate=candidate,
                author_candidates=author_candidates,
            )
    try:
        retrieve_recent_publications_for_candidate(
            db,
            candidate=candidate,
        )
    except ValueError as exc:
        return render_author_selection(
            request,
            candidate=candidate,
            author_candidates=[],
            error_message=str(exc),
        )
    response = workflow_or_selection_redirect(db, candidate)
    db.commit()
    return response


@router.post("/candidates/{candidate_id}/publications/openalex-author/confirm")
def candidate_confirm_openalex_author(
    request: Request,
    candidate_id: int,
    csrf: str = Form(...),
    selected_openalex_author_id: str = Form(...),
    db: Session = Depends(get_db),
) -> Response:
    validate_csrf_token(csrf)
    candidate = get_candidate(db, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404)
    try:
        candidate.openalex_author_id = normalize_openalex_author_id(selected_openalex_author_id)
        if not candidate_has_publications_for_openalex_author(
            db,
            candidate_id=candidate_id,
            openalex_author_id=candidate.openalex_author_id,
        ):
            retrieve_recent_publications_for_candidate(
                db,
                candidate=candidate,
                confirmed_openalex_author_id=candidate.openalex_author_id,
            )
    except ValueError as exc:
        return render_author_selection(
            request,
            candidate=candidate,
            author_candidates=[],
            error_message=str(exc),
        )
    response = workflow_or_selection_redirect(db, candidate)
    db.commit()
    return response


@router.post("/candidates/{candidate_id}/publications/openalex-author/reset")
def candidate_reset_openalex_author(
    candidate_id: int,
    csrf: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_csrf_token(csrf)
    candidate = get_candidate(db, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404)
    candidate.openalex_author_id = None
    db.commit()
    return RedirectResponse(f"/candidates/{candidate_id}", status_code=303)


@router.post("/candidates/{candidate_id}/publications/{publication_id}/approve")
def candidate_approve_publication_for_retrieval(
    candidate_id: int,
    publication_id: int,
    csrf: str = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_csrf_token(csrf)
    if get_candidate(db, candidate_id) is None:
        raise HTTPException(status_code=404)
    if db.get(Publication, publication_id) is None:
        raise HTTPException(status_code=404)
    try:
        approve_publication_for_retrieval(
            db,
            candidate_id=candidate_id,
            publication_id=publication_id,
            notes=notes or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return RedirectResponse(publication_selection_url(candidate_id), status_code=303)


@router.post("/candidates/{candidate_id}/publications/{publication_id}/retrieve")
def candidate_retrieve_publication_pdf(
    candidate_id: int,
    publication_id: int,
    csrf: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_csrf_token(csrf)
    candidate = get_candidate(db, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404)
    publication = db.get(Publication, publication_id)
    if publication is None:
        raise HTTPException(status_code=404)
    try:
        assert_publication_selected_for_retrieval(
            db,
            candidate_id=candidate_id,
            publication_id=publication_id,
        )
        paper_file = retrieve_publication_pdf(db, candidate=candidate, publication=publication)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return RedirectResponse(f"/papers/{paper_file.id}", status_code=303)
