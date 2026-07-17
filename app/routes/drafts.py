from typing import cast

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.security.csrf import csrf_token, validate_csrf_token
from app.services.drafting import approve_draft, get_draft, list_drafts, validate_draft_approval

router = APIRouter()


def render(request: Request, template_name: str, context: dict[str, object]) -> HTMLResponse:
    templates = request.app.state.templates
    base_context = request.app.state.base_context()
    base_context.update(context)
    return cast(HTMLResponse, templates.TemplateResponse(request, template_name, base_context))


@router.get("/drafts", response_class=HTMLResponse)
def drafts_index(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return render(
        request,
        "drafts.html",
        {
            "active_page": "drafts",
            "page_title": "Drafts",
            "drafts": list_drafts(db),
        },
    )


@router.get("/drafts/{draft_id}", response_class=HTMLResponse)
def draft_detail(request: Request, draft_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    draft = get_draft(db, draft_id)
    if draft is None:
        raise HTTPException(status_code=404)
    approval_errors = validate_draft_approval(db, draft=draft)
    return render(
        request,
        "draft_detail.html",
        {
            "active_page": "drafts",
            "page_title": draft.subject,
            "draft": draft,
            "approval_errors": approval_errors,
            "csrf_token": csrf_token(),
        },
    )


@router.post("/drafts/{draft_id}/approve")
def draft_approve(
    draft_id: int,
    csrf: str = Form(...),
    approval_ack: str | None = Form(None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_csrf_token(csrf)
    if approval_ack != "yes":
        raise HTTPException(status_code=400, detail="Approval checkbox is required.")
    draft = get_draft(db, draft_id)
    if draft is None:
        raise HTTPException(status_code=404)
    try:
        approve_draft(db, draft)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return RedirectResponse(f"/drafts/{draft_id}", status_code=303)
