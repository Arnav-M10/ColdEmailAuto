from typing import cast

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.paper import EvidenceClassification
from app.security.csrf import csrf_token, validate_csrf_token
from app.services.ai_analysis import arnav_profile_summary, create_ai_analysis_from_text
from app.services.ai_providers import AIProviderError
from app.services.analysis import (
    create_manual_analysis,
    create_structured_analysis_from_text,
    evidence_for_analysis,
    get_analysis,
    list_analyses_for_paper,
)
from app.services.candidates import get_candidate
from app.services.drafting import generate_manual_draft
from app.services.metadata import assert_publication_selected_for_retrieval
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
            "analyses": list_analyses_for_paper(db, paper_file.id),
            "csrf_token": csrf_token(),
        },
    )


@router.post("/papers/{paper_file_id}/analysis")
def paper_add_analysis(
    paper_file_id: int,
    csrf: str = Form(...),
    title: str = Form(...),
    research_question: str = Form(...),
    methods: str = Form(...),
    results: str = Form(...),
    connection_to_arnav: str = Form(...),
    claim: str = Form(...),
    evidence_text: str = Form(...),
    page_number: int = Form(...),
    section_name: str = Form("Unknown"),
    classification: EvidenceClassification = Form(...),
    confidence: float = Form(0.8),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_csrf_token(csrf)
    paper_file = get_paper_file(db, paper_file_id)
    if paper_file is None:
        raise HTTPException(status_code=404)
    candidate = get_candidate(db, paper_file.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404)
    if paper_file.publication_id is not None:
        try:
            assert_publication_selected_for_retrieval(
                db,
                candidate_id=candidate.id,
                publication_id=paper_file.publication_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    create_manual_analysis(
        db,
        candidate=candidate,
        paper_file=paper_file,
        title=title,
        research_question=research_question,
        methods=methods,
        results=results,
        connection_to_arnav=connection_to_arnav,
        claim=claim,
        evidence_text=evidence_text,
        page_number=page_number,
        section_name=section_name,
        classification=classification,
        confidence=confidence,
    )
    db.commit()
    return RedirectResponse(f"/papers/{paper_file_id}", status_code=303)


@router.post("/papers/{paper_file_id}/structured-analysis")
def paper_add_structured_analysis(
    paper_file_id: int,
    csrf: str = Form(...),
    title: str = Form(...),
    connection_to_arnav: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_csrf_token(csrf)
    paper_file = get_paper_file(db, paper_file_id)
    if paper_file is None:
        raise HTTPException(status_code=404)
    candidate = get_candidate(db, paper_file.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404)
    if paper_file.publication_id is not None:
        try:
            assert_publication_selected_for_retrieval(
                db,
                candidate_id=candidate.id,
                publication_id=paper_file.publication_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    create_structured_analysis_from_text(
        db,
        candidate=candidate,
        paper_file=paper_file,
        title=title,
        connection_to_arnav=connection_to_arnav,
    )
    db.commit()
    return RedirectResponse(f"/papers/{paper_file_id}", status_code=303)


@router.post("/papers/{paper_file_id}/ai-analysis")
def paper_add_ai_analysis(
    paper_file_id: int,
    csrf: str = Form(...),
    title: str = Form(...),
    connection_to_arnav: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_csrf_token(csrf)
    paper_file = get_paper_file(db, paper_file_id)
    if paper_file is None:
        raise HTTPException(status_code=404)
    candidate = get_candidate(db, paper_file.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404)
    if paper_file.publication_id is not None:
        try:
            assert_publication_selected_for_retrieval(
                db,
                candidate_id=candidate.id,
                publication_id=paper_file.publication_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        create_ai_analysis_from_text(
            db,
            candidate=candidate,
            paper_file=paper_file,
            title=title,
            connection_to_arnav=connection_to_arnav,
            profile_summary=arnav_profile_summary(),
        )
    except (AIProviderError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return RedirectResponse(f"/papers/{paper_file_id}", status_code=303)


@router.post("/analyses/{analysis_id}/draft")
def analysis_generate_draft(
    analysis_id: int,
    csrf: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_csrf_token(csrf)
    analysis = get_analysis(db, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404)
    candidate = get_candidate(db, analysis.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404)
    evidence = evidence_for_analysis(db, analysis.id)
    if not evidence:
        raise HTTPException(status_code=400, detail="Evidence is required before drafting.")
    draft = generate_manual_draft(db, candidate=candidate, analysis=analysis, evidence=evidence[0])
    db.commit()
    return RedirectResponse(f"/drafts/{draft.id}", status_code=303)
