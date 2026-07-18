from datetime import date
from typing import cast

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.candidate import CandidateStatus
from app.models.email_address import EmailAddress
from app.models.outreach import OutreachEvent
from app.models.paper import PaperFile
from app.models.publication import Publication
from app.security.csrf import csrf_token, validate_csrf_token
from app.services.candidates import (
    add_email_address,
    change_status,
    create_candidate,
    detect_duplicate_warnings,
    get_candidate,
    import_contacted_csv,
    list_candidates,
    preview_contacted_csv,
    soft_delete_candidate,
)
from app.services.followups import approved_drafts_for_candidate, list_follow_ups_for_candidate
from app.services.metadata import list_candidate_publication_reviews
from app.services.papers import store_manual_pdf
from app.services.research_workflow import (
    latest_workflow_run,
    run_research_workflow,
    workflow_review_context,
)

router = APIRouter()


def render(request: Request, template_name: str, context: dict[str, object]) -> HTMLResponse:
    templates = request.app.state.templates
    base_context = request.app.state.base_context()
    base_context.update(context)
    return cast(HTMLResponse, templates.TemplateResponse(request, template_name, base_context))


@router.get("/candidates", response_class=HTMLResponse)
def candidates_index(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return render(
        request,
        "candidates.html",
        {
            "active_page": "candidates",
            "page_title": "Candidates",
            "candidates": list_candidates(db),
            "csrf_token": csrf_token(),
        },
    )


@router.post("/candidates")
def candidates_create(
    csrf: str = Form(...),
    full_name: str = Form(...),
    title: str = Form(""),
    institution: str = Form(""),
    department: str = Form(""),
    research_area: str = Form(""),
    official_profile_url: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_csrf_token(csrf)
    if not full_name.strip():
        raise HTTPException(status_code=400, detail="Candidate name is required.")
    create_candidate(
        db,
        full_name=full_name,
        title=title,
        institution=institution,
        department=department,
        research_area=research_area,
        official_profile_url=official_profile_url,
        notes=notes,
    )
    db.commit()
    return RedirectResponse("/candidates", status_code=303)


@router.get("/candidates/{candidate_id}", response_class=HTMLResponse)
def candidate_detail(
    request: Request,
    candidate_id: int,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    candidate = get_candidate(db, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404)
    emails = list(
        db.scalars(
            select(EmailAddress)
            .where(EmailAddress.candidate_id == candidate_id)
            .order_by(EmailAddress.created_at.desc()),
        ),
    )
    events = list(
        db.scalars(
            select(OutreachEvent)
            .where(OutreachEvent.candidate_id == candidate_id)
            .order_by(OutreachEvent.created_at.desc()),
        ),
    )
    workflow = latest_workflow_run(db, candidate_id)
    workflow_context = workflow_review_context(db, workflow=workflow)
    selected_publication = (
        db.get(Publication, workflow.selected_publication_id)
        if workflow and workflow.selected_publication_id
        else None
    )
    selected_paper_file = (
        db.get(PaperFile, workflow.paper_file_id) if workflow and workflow.paper_file_id else None
    )
    return render(
        request,
        "candidate_detail.html",
        {
            "active_page": "candidates",
            "page_title": candidate.full_name,
            "candidate": candidate,
            "emails": emails,
            "events": events,
            "approved_draft_count": len(approved_drafts_for_candidate(db, candidate_id)),
            "follow_up_tasks": list_follow_ups_for_candidate(db, candidate_id),
            "publication_reviews": list_candidate_publication_reviews(db, candidate_id),
            "selected_publication": selected_publication,
            "selected_paper_file": selected_paper_file,
            **workflow_context,
            "statuses": list(CandidateStatus),
            "today": date.today().isoformat(),
            "csrf_token": csrf_token(),
        },
    )


@router.post("/candidates/{candidate_id}/emails")
def candidate_add_email(
    candidate_id: int,
    csrf: str = Form(...),
    email: str = Form(...),
    source_url: str = Form(...),
    source_type: str = Form(...),
    confidence: str = Form("MEDIUM"),
    verification_status: str = Form("VERIFIED"),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_csrf_token(csrf)
    if get_candidate(db, candidate_id) is None:
        raise HTTPException(status_code=404)
    add_email_address(
        db,
        candidate_id=candidate_id,
        email=email,
        source_url=source_url,
        source_type=source_type,
        confidence=confidence,
        verification_status=verification_status,
    )
    db.commit()
    return RedirectResponse(f"/candidates/{candidate_id}", status_code=303)


@router.post("/candidates/{candidate_id}/research-workflow/run")
def candidate_run_research_workflow(
    candidate_id: int,
    csrf: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_csrf_token(csrf)
    candidate = get_candidate(db, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404)
    workflow = run_research_workflow(db, candidate=candidate)
    db.commit()
    if workflow.draft_id is not None:
        return RedirectResponse(f"/drafts/{workflow.draft_id}/manual-review", status_code=303)
    if workflow.paper_file_id is not None:
        return RedirectResponse(f"/papers/{workflow.paper_file_id}", status_code=303)
    if workflow.selected_publication_id is not None:
        return RedirectResponse(f"/candidates/{candidate_id}/publications/select", status_code=303)
    return RedirectResponse(f"/candidates/{candidate_id}", status_code=303)


@router.post("/candidates/{candidate_id}/papers")
async def candidate_upload_paper(
    candidate_id: int,
    csrf: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_csrf_token(csrf)
    candidate = get_candidate(db, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404)
    content = await file.read()
    try:
        store_manual_pdf(
            db,
            candidate=candidate,
            original_filename=file.filename or "uploaded.pdf",
            content=content,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return RedirectResponse(f"/candidates/{candidate_id}", status_code=303)


@router.post("/candidates/{candidate_id}/status")
def candidate_change_status(
    candidate_id: int,
    csrf: str = Form(...),
    status: CandidateStatus = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_csrf_token(csrf)
    candidate = get_candidate(db, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404)
    try:
        change_status(db, candidate, status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return RedirectResponse(f"/candidates/{candidate_id}", status_code=303)


@router.post("/candidates/{candidate_id}/delete")
def candidate_delete(
    candidate_id: int,
    csrf: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_csrf_token(csrf)
    candidate = get_candidate(db, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404)
    soft_delete_candidate(db, candidate)
    db.commit()
    return RedirectResponse("/candidates", status_code=303)


@router.post("/candidates/duplicate-check", response_class=HTMLResponse)
def duplicate_check(
    request: Request,
    full_name: str = Form(...),
    institution: str = Form(""),
    email: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    warnings = detect_duplicate_warnings(
        db,
        full_name=full_name,
        institution=institution,
        email=email or None,
    )
    return render(request, "partials/duplicate_warnings.html", {"duplicate_warnings": warnings})


@router.get("/contact-history", response_class=HTMLResponse)
def contact_history(request: Request) -> HTMLResponse:
    return render(
        request,
        "contact_history.html",
        {
            "active_page": "contact_history",
            "page_title": "Contact History",
            "preview_rows": [],
            "import_result": None,
            "csrf_token": csrf_token(),
        },
    )


@router.post("/contact-history/preview", response_class=HTMLResponse)
async def contact_history_preview(
    request: Request,
    csrf: str = Form(...),
    file: UploadFile = File(...),
) -> HTMLResponse:
    validate_csrf_token(csrf)
    content = await file.read()
    preview_rows = preview_contacted_csv(content.decode("utf-8-sig"))
    return render(
        request,
        "contact_history.html",
        {
            "active_page": "contact_history",
            "page_title": "Contact History",
            "preview_rows": preview_rows,
            "import_result": None,
            "csrf_token": csrf_token(),
        },
    )


@router.post("/contact-history/import", response_class=HTMLResponse)
async def contact_history_import(
    request: Request,
    csrf: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    validate_csrf_token(csrf)
    content = await file.read()
    result = import_contacted_csv(db, content.decode("utf-8-sig"))
    db.commit()
    return render(
        request,
        "contact_history.html",
        {
            "active_page": "contact_history",
            "page_title": "Contact History",
            "preview_rows": [],
            "import_result": result,
            "csrf_token": csrf_token(),
        },
    )
