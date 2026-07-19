import hmac
from typing import cast

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import get_settings
from app.security.csrf import csrf_token, validate_csrf_token
from app.services.assets import build_asset_manifest, store_private_pdf_upload
from app.services.metadata import load_research_portfolio_text_status

router = APIRouter()


def render(request: Request, template_name: str, context: dict[str, object]) -> HTMLResponse:
    templates = request.app.state.templates
    base_context = request.app.state.base_context()
    base_context.update(context)
    return cast(HTMLResponse, templates.TemplateResponse(request, template_name, base_context))


def validate_admin_setup_token(provided: str) -> None:
    expected = get_settings().admin_setup_token
    if not expected:
        raise HTTPException(
            status_code=403,
            detail="ADMIN_SETUP_TOKEN must be configured before private asset setup.",
        )
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="Invalid admin setup token.")


@router.get("/settings/private-assets", response_class=HTMLResponse)
def private_asset_setup_page(
    request: Request,
    admin_token: str = Query(""),
    candidate_id: int | None = Query(None),
) -> HTMLResponse:
    try:
        validate_admin_setup_token(admin_token)
    except HTTPException as exc:
        response = render(
            request,
            "private_asset_setup.html",
            {
                "active_page": "settings",
                "page_title": "Private Asset Setup",
                "setup_locked": True,
                "setup_error": exc.detail,
                "candidate_id": candidate_id,
                "asset_manifest": build_asset_manifest(),
                "portfolio_input_status": load_research_portfolio_text_status(),
            },
        )
        response.status_code = 403
        return response
    return render(
        request,
        "private_asset_setup.html",
        {
            "active_page": "settings",
            "page_title": "Private Asset Setup",
            "csrf_token": csrf_token(),
            "admin_token": admin_token,
            "candidate_id": candidate_id,
            "asset_manifest": build_asset_manifest(),
            "portfolio_input_status": load_research_portfolio_text_status(),
        },
    )


@router.post("/settings/private-assets/upload")
async def private_asset_upload(
    csrf: str = Form(...),
    admin_token: str = Form(...),
    candidate_id: int | None = Form(None),
    resume_pdf: UploadFile | None = File(None),
    portfolio_pdf: UploadFile | None = File(None),
) -> RedirectResponse:
    try:
        validate_csrf_token(csrf)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    validate_admin_setup_token(admin_token)
    settings = get_settings()
    max_size_bytes = settings.max_pdf_size_mb * 1024 * 1024
    uploaded_any = False
    try:
        if resume_pdf and resume_pdf.filename:
            store_private_pdf_upload(
                label="Resume",
                destination=settings.resolved_resume_pdf_path,
                content=await resume_pdf.read(),
                content_type=resume_pdf.content_type,
                max_size_bytes=max_size_bytes,
            )
            uploaded_any = True
        if portfolio_pdf and portfolio_pdf.filename:
            store_private_pdf_upload(
                label="Research portfolio",
                destination=settings.resolved_research_portfolio_pdf_path,
                content=await portfolio_pdf.read(),
                content_type=portfolio_pdf.content_type,
                max_size_bytes=max_size_bytes,
                require_text=True,
            )
            load_research_portfolio_text_status()
            uploaded_any = True
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not uploaded_any:
        raise HTTPException(status_code=400, detail="Upload at least one private PDF.")
    target = f"/candidates/{candidate_id}" if candidate_id else "/settings"
    return RedirectResponse(target, status_code=303)
