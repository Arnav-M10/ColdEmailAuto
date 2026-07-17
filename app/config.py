from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    ai_model: str = Field(default="gemini-2.5-flash", validation_alias="AI_MODEL")
    ai_api_key: str | None = Field(default=None, validation_alias="AI_API_KEY")
    gemini_api_key: str | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    ai_timeout_seconds: float = Field(default=30.0, validation_alias="AI_TIMEOUT_SECONDS")
    ai_retries: int = Field(default=2, validation_alias="AI_RETRIES")
    ai_temperature: float = Field(default=0.1, validation_alias="AI_TEMPERATURE")
    ai_max_tokens: int = Field(default=4096, validation_alias="AI_MAX_TOKENS")
    project_root: Path = Path(__file__).resolve().parent.parent
    assets_dir: Path = project_root / "assets"
    logs_dir: Path = project_root / "logs"
    drafts_only_mode: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
