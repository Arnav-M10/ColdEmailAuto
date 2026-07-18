from typing import cast

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.security.csrf import csrf_token, validate_csrf_token
from app.services.drafting import (
    approve_draft,
    get_draft,
    list_drafts,
    validate_draft_approval,
    word_count,
)
from app.services.review import manual_review_context

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


@router.get("/drafts/{draft_id}/manual-review", response_class=HTMLResponse)
def draft_manual_review(
    request: Request,
    draft_id: int,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    draft = get_draft(db, draft_id)
    if draft is None:
        raise HTTPException(status_code=404)
    review = manual_review_context(db, draft=draft)
    return render(
        request,
        "manual_review.html",
        {
            "active_page": "drafts",
            "page_title": "Manual Outlook Review",
            "review": review,
            "draft": draft,
            "csrf_token": csrf_token(),
        },
    )


@router.post("/drafts/{draft_id}/edit")
def draft_edit(
    draft_id: int,
    csrf: str = Form(...),
    subject: str = Form(...),
    body_text: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_csrf_token(csrf)
    draft = get_draft(db, draft_id)
    if draft is None:
        raise HTTPException(status_code=404)
    draft.subject = subject.strip()
    draft.body_text = body_text.strip()
    draft.word_count = word_count(draft.body_text)
    draft.approved_by_user = False
    draft.approved_at = None
    db.commit()
    return RedirectResponse(f"/drafts/{draft_id}/manual-review", status_code=303)


@router.post("/drafts/{draft_id}/regenerate")
def draft_regenerate(
    draft_id: int,
    csrf: str = Form(...),
    variant: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_csrf_token(csrf)
    draft = get_draft(db, draft_id)
    if draft is None:
        raise HTTPException(status_code=404)
    draft.body_text = regenerate_variant(draft.body_text, variant)
    draft.word_count = word_count(draft.body_text)
    draft.approved_by_user = False
    draft.approved_at = None
    db.commit()
    return RedirectResponse(f"/drafts/{draft_id}/manual-review", status_code=303)


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


def regenerate_variant(body: str, variant: str) -> str:
    if variant == "shorter":
        return body.replace(" for context", "")
    if variant == "simpler":
        return body.replace("numerical checks", "number checks")
    if variant == "more_personal":
        return body.replace(
            "I would be glad to help",
            "I would be excited to help",
        )
    if variant == "less_technical":
        return body.replace(
            "data analysis, numerical checks, or visualization",
            "data work or plots",
        )
    if variant == "another_detail":
        return body.replace("I was mainly intrigued by", "The detail that stood out to me was")
    return body
