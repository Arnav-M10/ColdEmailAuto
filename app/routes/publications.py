from typing import cast

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.publication import Publication
from app.security.csrf import validate_csrf_token
from app.services.candidates import get_candidate
from app.services.metadata import (
    list_publications,
    manual_publication_metadata,
    upsert_publication_with_authorship,
)
from app.services.retrieval import retrieve_publication_pdf

router = APIRouter()


def render(request: Request, template_name: str, context: dict[str, object]) -> HTMLResponse:
    templates = request.app.state.templates
    base_context = request.app.state.base_context()
    base_context.update(context)
    return cast(HTMLResponse, templates.TemplateResponse(request, template_name, base_context))


@router.get("/publications", response_class=HTMLResponse)
def publications_index(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return render(
        request,
        "publications.html",
        {
            "active_page": "publications",
            "page_title": "Publications",
            "publications": list_publications(db),
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
    return RedirectResponse(f"/candidates/{candidate_id}", status_code=303)


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
        retrieve_publication_pdf(db, candidate=candidate, publication=publication)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return RedirectResponse(f"/candidates/{candidate_id}", status_code=303)
