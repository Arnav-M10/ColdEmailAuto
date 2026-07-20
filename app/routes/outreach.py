import logging
from time import sleep
from typing import cast

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.session import get_db, is_sqlite_lock_error
from app.security.csrf import csrf_token, validate_csrf_token
from app.services.candidates import get_candidate
from app.services.drafting import get_draft
from app.services.outreach_agent import OutreachAgentResult, load_draft_ai_review, start_outreach
from app.services.review import manual_review_context

router = APIRouter()
logger = logging.getLogger("professor_outreach.outreach")
SQLITE_LOCK_RETRY_DELAYS = (0.15, 0.45)


def render(request: Request, template_name: str, context: dict[str, object]) -> HTMLResponse:
    templates = request.app.state.templates
    base_context = request.app.state.base_context()
    base_context.update(context)
    return cast(HTMLResponse, templates.TemplateResponse(request, template_name, base_context))


@router.get("/outreach", response_class=HTMLResponse)
def outreach_home(request: Request) -> HTMLResponse:
    return render(
        request,
        "outreach.html",
        {
            "active_page": "outreach",
            "page_title": "Start Outreach",
            "csrf_token": csrf_token(),
            "result": None,
        },
    )


@router.post("/outreach/start", response_class=HTMLResponse, response_model=None)
def outreach_start(
    request: Request,
    csrf: str = Form(...),
    db: Session = Depends(get_db),
) -> HTMLResponse | RedirectResponse:
    validate_csrf_token(csrf)
    result = start_outreach_with_sqlite_lock_retry(db)
    if result.success and result.draft is not None:
        return RedirectResponse(f"/outreach/drafts/{result.draft.id}", status_code=303)
    return render(
        request,
        "outreach.html",
        {
            "active_page": "outreach",
            "page_title": "Start Outreach",
            "csrf_token": csrf_token(),
            "result": result,
        },
    )


def start_outreach_with_sqlite_lock_retry(db: Session) -> OutreachAgentResult:
    for attempt in range(len(SQLITE_LOCK_RETRY_DELAYS) + 1):
        try:
            result = start_outreach(db, commit_checkpoints=True)
            db.commit()
            return result
        except OperationalError as exc:
            db.rollback()
            if not is_sqlite_lock_error(exc) or attempt >= len(SQLITE_LOCK_RETRY_DELAYS):
                raise
            delay = SQLITE_LOCK_RETRY_DELAYS[attempt]
            logger.warning(
                "sqlite_lock_retry",
                extra={
                    "attempt": attempt + 1,
                    "retry_delay_seconds": delay,
                    "reason": str(exc.orig),
                },
            )
            db.expire_all()
            sleep(delay)
    raise RuntimeError("unreachable sqlite lock retry state")


@router.get("/outreach/drafts/{draft_id}", response_class=HTMLResponse)
def outreach_draft(
    request: Request,
    draft_id: int,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    draft = get_draft(db, draft_id)
    if draft is None:
        raise HTTPException(status_code=404)
    review = manual_review_context(db, draft=draft)
    candidate = get_candidate(db, draft.candidate_id)
    return render(
        request,
        "outreach_result.html",
        {
            "active_page": "outreach",
            "page_title": "Finished Draft",
            "draft": draft,
            "candidate": candidate,
            "review": review,
            "ai_review": load_draft_ai_review(draft),
            "csrf_token": csrf_token(),
        },
    )
