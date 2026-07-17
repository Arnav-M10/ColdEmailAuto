from typing import cast

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.security.csrf import csrf_token, validate_csrf_token
from app.services.discovery import (
    create_department_import,
    extract_department_candidates,
    get_department_import,
    get_discovery_candidate,
    list_department_imports,
    list_discovery_candidates,
    reject_discovery_candidate,
    save_discovery_candidate,
)
from app.services.web_safety import SafeFetcher, SafeFetchError

router = APIRouter()


def render(request: Request, template_name: str, context: dict[str, object]) -> HTMLResponse:
    templates = request.app.state.templates
    base_context = request.app.state.base_context()
    base_context.update(context)
    return cast(HTMLResponse, templates.TemplateResponse(request, template_name, base_context))


@router.get("/discovery", response_class=HTMLResponse)
def discovery_index(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return render(
        request,
        "discovery.html",
        {
            "active_page": "discovery",
            "page_title": "Discovery",
            "imports": list_department_imports(db),
            "csrf_token": csrf_token(),
        },
    )


@router.post("/discovery/import")
def discovery_import(
    csrf: str = Form(...),
    source_url: str = Form(...),
    institution: str = Form(""),
    department: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_csrf_token(csrf)
    fetcher = SafeFetcher()
    try:
        fetch_result = fetcher.fetch(source_url, expected="html")
    except SafeFetchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    previews = extract_department_candidates(
        fetch_result.body.decode("utf-8", errors="replace"),
        source_url=fetch_result.final_url,
        institution=institution or None,
        department=department or None,
    )
    department_import = create_department_import(
        db,
        source_url=source_url,
        fetch_result=fetch_result,
        previews=previews,
        institution=institution or None,
        department=department or None,
    )
    db.commit()
    return RedirectResponse(f"/discovery/imports/{department_import.id}", status_code=303)


@router.get("/discovery/imports/{import_id}", response_class=HTMLResponse)
def discovery_import_detail(
    request: Request,
    import_id: int,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    department_import = get_department_import(db, import_id)
    if department_import is None:
        raise HTTPException(status_code=404)
    return render(
        request,
        "discovery_detail.html",
        {
            "active_page": "discovery",
            "page_title": "Discovery Review",
            "department_import": department_import,
            "candidates": list_discovery_candidates(db, import_id),
            "csrf_token": csrf_token(),
        },
    )


@router.post("/discovery/candidates/{preview_id}/reject")
def discovery_candidate_reject(
    preview_id: int,
    csrf: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_csrf_token(csrf)
    preview = get_discovery_candidate(db, preview_id)
    if preview is None:
        raise HTTPException(status_code=404)
    reject_discovery_candidate(db, preview)
    db.commit()
    return RedirectResponse(f"/discovery/imports/{preview.import_id}", status_code=303)


@router.post("/discovery/candidates/{preview_id}/save")
def discovery_candidate_save(
    preview_id: int,
    csrf: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_csrf_token(csrf)
    preview = get_discovery_candidate(db, preview_id)
    if preview is None:
        raise HTTPException(status_code=404)
    try:
        candidate = save_discovery_candidate(db, preview)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return RedirectResponse(f"/candidates/{candidate.id}", status_code=303)
