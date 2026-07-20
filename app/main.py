import logging
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.config import get_settings
from app.db.session import check_database, get_db, initialize_database
from app.observability.logging import configure_logging
from app.routes.candidates import router as candidates_router
from app.routes.discovery import router as discovery_router
from app.routes.drafts import router as drafts_router
from app.routes.followups import router as followups_router
from app.routes.outreach import router as outreach_router
from app.routes.papers import router as papers_router
from app.routes.publications import router as publications_router
from app.routes.settings import router as settings_router
from app.safety import assert_no_send_capability
from app.security.csrf import csrf_token
from app.security.headers import apply_security_headers
from app.services.assets import build_asset_manifest
from app.services.profile import load_profile

settings = get_settings()
templates = Jinja2Templates(directory=str(settings.project_root / "app" / "templates"))
logger = logging.getLogger("professor_outreach.requests")


def create_app() -> FastAPI:
    configure_logging()
    assert_no_send_capability()
    initialize_database()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/api/docs" if settings.app_env == "development" else None,
        redoc_url=None,
    )
    app.mount(
        "/static",
        StaticFiles(directory=str(settings.project_root / "app" / "static")),
        name="static",
    )
    app.state.templates = templates
    app.state.base_context = base_context
    app.include_router(candidates_router)
    app.include_router(discovery_router)
    app.include_router(drafts_router)
    app.include_router(followups_router)
    app.include_router(outreach_router)
    app.include_router(papers_router)
    app.include_router(publications_router)
    app.include_router(settings_router)

    @app.middleware("http")
    async def request_observability_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        start = perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        apply_security_headers(response)
        duration_ms = round((perf_counter() - start) * 1000, 2)
        logger.info(
            "http_request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request, db: Annotated[Session, Depends(get_db)]) -> HTMLResponse:
        del db
        return render_page(
            request=request,
            template_name="outreach.html",
            active_page="outreach",
            page_title="Start Outreach",
            extra_context={"result": None, "csrf_token": csrf_token()},
        )

    @app.get("/health", response_class=HTMLResponse)
    def health_page(request: Request) -> HTMLResponse:
        return render_page(
            request=request,
            template_name="health.html",
            active_page="health",
            page_title="Health",
        )

    @app.get("/api/health")
    def health_check() -> dict[str, str | bool]:
        return {
            "status": "ok",
            "app": settings.app_name,
            "environment": settings.app_env,
            "drafts_only": settings.drafts_only_mode,
            "database": check_database(),
        }

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request) -> HTMLResponse:
        return render_page(
            request=request,
            template_name="settings.html",
            active_page="settings",
            page_title="Settings",
        )

    return app


def render_page(
    *,
    request: Request,
    template_name: str,
    active_page: str,
    page_title: str,
    extra_context: dict[str, object] | None = None,
) -> HTMLResponse:
    context = base_context(active_page=active_page, page_title=page_title)
    if extra_context:
        context.update(extra_context)
    return templates.TemplateResponse(request, template_name, context)


def base_context(active_page: str = "", page_title: str = "") -> dict[str, object]:
    return {
        "active_page": active_page,
        "page_title": page_title,
        "settings": settings,
        "asset_manifest": build_asset_manifest(),
        "profile": load_profile(),
    }


app = create_app()
