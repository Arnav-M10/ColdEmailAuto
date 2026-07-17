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
    project_root: Path = Path(__file__).resolve().parent.parent
    assets_dir: Path = project_root / "assets"
    logs_dir: Path = project_root / "logs"
    drafts_only_mode: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
