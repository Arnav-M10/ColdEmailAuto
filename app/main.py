import logging
from collections.abc import Awaitable, Callable
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from app.config import get_settings
from app.db.session import check_database, initialize_database
from app.observability.logging import configure_logging
from app.safety import assert_no_send_capability
from app.security.headers import apply_security_headers

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
    def dashboard(request: Request) -> HTMLResponse:
        return render_page(
            request=request,
            template_name="dashboard.html",
            active_page="dashboard",
            page_title="Dashboard",
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

    @app.get("/candidates", response_class=HTMLResponse)
    def candidates_page(request: Request) -> HTMLResponse:
        return render_page(
            request=request,
            template_name="candidates.html",
            active_page="candidates",
            page_title="Candidates",
        )

    @app.get("/papers", response_class=HTMLResponse)
    def papers_page(request: Request) -> HTMLResponse:
        return render_page(
            request=request,
            template_name="papers.html",
            active_page="papers",
            page_title="Papers",
        )

    @app.get("/drafts", response_class=HTMLResponse)
    def drafts_page(request: Request) -> HTMLResponse:
        return render_page(
            request=request,
            template_name="drafts.html",
            active_page="drafts",
            page_title="Drafts",
        )

    return app


def render_page(
    *,
    request: Request,
    template_name: str,
    active_page: str,
    page_title: str,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        template_name,
        {
            "active_page": active_page,
            "page_title": page_title,
            "settings": settings,
        },
    )


app = create_app()
