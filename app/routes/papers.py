from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.papers import get_paper_file, list_paper_files, read_parsed_text

router = APIRouter()


def render(request: Request, template_name: str, context: dict[str, object]) -> HTMLResponse:
    templates = request.app.state.templates
    base_context = request.app.state.base_context()
    base_context.update(context)
    return cast(HTMLResponse, templates.TemplateResponse(request, template_name, base_context))


@router.get("/papers", response_class=HTMLResponse)
def papers_index(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return render(
        request,
        "papers.html",
        {
            "active_page": "papers",
            "page_title": "Papers",
            "papers": list_paper_files(db),
        },
    )


@router.get("/papers/{paper_file_id}", response_class=HTMLResponse)
def paper_detail(
    request: Request,
    paper_file_id: int,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    paper_file = get_paper_file(db, paper_file_id)
    if paper_file is None:
        raise HTTPException(status_code=404)
    return render(
        request,
        "paper_detail.html",
        {
            "active_page": "papers",
            "page_title": paper_file.original_filename,
            "paper": paper_file,
            "parsed_text": read_parsed_text(paper_file)[:4000],
        },
    )
