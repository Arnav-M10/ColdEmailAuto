from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed local application settings with safe defaults."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

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
    project_root: Path = Path(__file__).resolve().parent.parent
    assets_dir: Path = project_root / "assets"
    logs_dir: Path = project_root / "logs"
    drafts_only_mode: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
