from datetime import date
from typing import cast

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.candidate import Candidate
from app.security.csrf import csrf_token, validate_csrf_token
from app.services.candidates import get_candidate
from app.services.followups import (
    complete_follow_up_task,
    get_follow_up_task,
    list_follow_up_tasks,
    mark_candidate_manually_sent_and_schedule_follow_up,
)

router = APIRouter()


def render(request: Request, template_name: str, context: dict[str, object]) -> HTMLResponse:
    templates = request.app.state.templates
    base_context = request.app.state.base_context()
    base_context.update(context)
    return cast(HTMLResponse, templates.TemplateResponse(request, template_name, base_context))


@router.get("/follow-ups", response_class=HTMLResponse)
def follow_ups_index(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    tasks = list_follow_up_tasks(db)
    candidate_ids = {task.candidate_id for task in tasks}
    candidates = {
        candidate.id: candidate
        for candidate in db.query(Candidate).filter(Candidate.id.in_(candidate_ids)).all()
    }
    return render(
        request,
        "follow_ups.html",
        {
            "active_page": "follow_ups",
            "page_title": "Follow-Ups",
            "tasks": tasks,
            "candidates": candidates,
            "today": date.today(),
            "csrf_token": csrf_token(),
        },
    )


@router.post("/candidates/{candidate_id}/mark-sent")
def candidate_mark_sent(
    candidate_id: int,
    csrf: str = Form(...),
    sent_on: date = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_csrf_token(csrf)
    candidate = get_candidate(db, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404)
    try:
        mark_candidate_manually_sent_and_schedule_follow_up(
            db,
            candidate=candidate,
            sent_on=sent_on,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return RedirectResponse(f"/candidates/{candidate_id}", status_code=303)


@router.post("/follow-ups/{task_id}/complete")
def follow_up_complete(
    task_id: int,
    csrf: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_csrf_token(csrf)
    task = get_follow_up_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=404)
    complete_follow_up_task(db, task)
    db.commit()
    return RedirectResponse("/follow-ups", status_code=303)
