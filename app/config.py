import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

RAILWAY_ENV_KEYS = ("RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID")


def railway_runtime_detected() -> bool:
    return any(os.getenv(key) for key in RAILWAY_ENV_KEYS)


def normalize_sqlite_database_url(
    database_url: str,
    *,
    railway_runtime: bool | None = None,
) -> str:
    if database_url.startswith("sqlite:////"):
        return database_url
    if not database_url.startswith("sqlite:///data/"):
        return database_url
    runtime_is_railway = (
        railway_runtime if railway_runtime is not None else railway_runtime_detected()
    )
    if runtime_is_railway:
        return f"sqlite:////data/{database_url.removeprefix('sqlite:///data/')}"
    return database_url


class Settings(BaseSettings):
    """Typed local application settings with safe defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "Professor Outreach Manager"
    app_env: str = Field(default="development", validation_alias="APP_ENV")
    app_host: str = Field(default="127.0.0.1", validation_alias="APP_HOST")
    app_port: int = Field(default=8000, validation_alias="APP_PORT")
    database_url: str = Field(default="sqlite:///data/outreach.db", validation_alias="DATABASE_URL")
    csrf_secret: str = Field(
        default="local-development-csrf-secret",
        validation_alias="CSRF_SECRET",
    )
    max_pdf_size_mb: int = Field(default=25, validation_alias="MAX_PDF_SIZE_MB")
    max_html_size_mb: int = Field(default=3, validation_alias="MAX_HTML_SIZE_MB")
    http_timeout_seconds: float = Field(default=12.0, validation_alias="HTTP_TIMEOUT_SECONDS")
    http_max_redirects: int = Field(default=5, validation_alias="HTTP_MAX_REDIRECTS")
    http_min_domain_delay_seconds: float = Field(
        default=1.0,
        validation_alias="HTTP_MIN_DOMAIN_DELAY_SECONDS",
    )
    http_user_agent: str = Field(
        default="ProfessorOutreachManager/0.1 (+local human-supervised research assistant)",
        validation_alias="HTTP_USER_AGENT",
    )
    ai_provider: str = Field(default="gemini", validation_alias="AI_PROVIDER")
    ai_model: str = Field(default="gemini-3.5-flash", validation_alias="AI_MODEL")
    ai_api_key: str | None = Field(default=None, validation_alias="AI_API_KEY")
    gemini_api_key: str | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    ai_timeout_seconds: float = Field(default=30.0, validation_alias="AI_TIMEOUT_SECONDS")
    ai_retries: int = Field(default=2, validation_alias="AI_RETRIES")
    ai_temperature: float = Field(default=0.1, validation_alias="AI_TEMPERATURE")
    ai_max_tokens: int = Field(default=4096, validation_alias="AI_MAX_TOKENS")
    ai_daily_request_limit: int = Field(default=25, validation_alias="AI_DAILY_REQUEST_LIMIT")
    ai_max_requests_per_workflow: int = Field(
        default=2,
        validation_alias="AI_MAX_REQUESTS_PER_WORKFLOW",
    )
    ai_require_free_tier: bool = Field(default=True, validation_alias="AI_REQUIRE_FREE_TIER")
    auto_select_paper: bool = Field(default=True, validation_alias="AUTO_SELECT_PAPER")
    runtime_data_dir: Path = Field(default=Path("data"), validation_alias="RUNTIME_DATA_DIR")
    private_asset_dir: Path = Field(
        default=Path("/data/private_assets"),
        validation_alias="PRIVATE_ASSET_DIR",
    )
    resume_pdf_path: Path | None = Field(default=None, validation_alias="RESUME_PDF_PATH")
    research_portfolio_pdf_path: Path | None = Field(
        default=None,
        validation_alias="RESEARCH_PORTFOLIO_PDF_PATH",
    )
    admin_setup_token: str | None = Field(default=None, validation_alias="ADMIN_SETUP_TOKEN")
    project_root: Path = Path(__file__).resolve().parent.parent
    assets_dir: Path = project_root / "assets"
    logs_dir: Path = project_root / "logs"
    drafts_only_mode: bool = True

    def resolve_path(self, path: Path) -> Path:
        return path if path.is_absolute() else self.project_root / path

    @property
    def resolved_private_asset_dir(self) -> Path:
        return self.resolve_path(self.private_asset_dir)

    @property
    def effective_database_url(self) -> str:
        return normalize_sqlite_database_url(self.database_url)

    @property
    def resolved_runtime_data_dir(self) -> Path:
        return self.resolve_path(self.runtime_data_dir)

    @property
    def resolved_resume_pdf_path(self) -> Path:
        return self.resolve_path(
            self.resume_pdf_path or self.resolved_private_asset_dir / "arnav_resume.pdf",
        )

    @property
    def resolved_research_portfolio_pdf_path(self) -> Path:
        return self.resolve_path(
            self.research_portfolio_pdf_path
            or self.resolved_private_asset_dir / "arnav_research_portfolio.pdf",
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
