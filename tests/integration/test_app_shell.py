from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.security.csrf import csrf_token


def test_health_check_reports_drafts_only_mode() -> None:
    client = TestClient(create_app())

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["drafts_only"] is True


def test_placeholder_pages_render() -> None:
    client = TestClient(create_app())

    for path in ["/", "/health", "/settings", "/candidates", "/papers", "/drafts"]:
        response = client.get(path)
        assert response.status_code == 200
        assert "Drafts-only mode" in response.text
        assert "No Mail.Send" in response.text


def test_static_assets_render_as_same_origin_paths_and_load() -> None:
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert 'href="/static/favicon.svg"' in response.text
    assert 'href="/static/styles.css"' in response.text
    assert "http://testserver/static/styles.css" not in response.text

    favicon = client.get("/static/favicon.svg")
    assert favicon.status_code == 200
    assert favicon.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in favicon.text

    styles = client.get("/static/styles.css")
    assert styles.status_code == 200
    assert styles.headers["content-type"].startswith("text/css")
    assert ".app-shell" in styles.text

    script = client.get("/static/manual_review.js")
    assert script.status_code == 200
    assert script.headers["content-type"].startswith("text/javascript")
    assert "copyText" in script.text


def test_settings_page_shows_required_assets() -> None:
    client = TestClient(create_app())

    response = client.get("/settings")

    assert response.status_code == 200
    assert "Required assets" in response.text
    assert "arnav_resume.pdf" in response.text
    assert "arnav_research_portfolio.pdf" in response.text


def test_private_asset_setup_rejects_missing_or_wrong_admin_token() -> None:
    client = TestClient(create_app())

    missing = client.get("/settings/private-assets")
    wrong = client.get("/settings/private-assets?admin_token=wrong")
    upload = client.post(
        "/settings/private-assets/upload",
        data={"csrf": csrf_token(), "admin_token": "wrong"},
    )

    assert missing.status_code == 403
    assert wrong.status_code == 403
    assert upload.status_code == 403


def test_private_asset_setup_uploads_files_without_public_access(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    private_dir = tmp_path / "private_assets"
    settings = get_settings().model_copy(
        update={
            "private_asset_dir": private_dir,
            "resume_pdf_path": private_dir / "arnav_resume.pdf",
            "research_portfolio_pdf_path": private_dir / "arnav_research_portfolio.pdf",
            "admin_setup_token": "setup-secret",
            "project_root": tmp_path,
        },
    )

    class TextPage:
        def extract_text(self) -> str:
            return "compact binaries time-domain astrophysics"

    class TextReader:
        is_encrypted = False

        def __init__(self, _source: object) -> None:
            self.pages = [TextPage()]

    monkeypatch.setattr("app.routes.settings.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.assets.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.assets.PdfReader", TextReader)
    monkeypatch.setattr("app.services.metadata.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.metadata.PdfReader", TextReader)

    client = TestClient(create_app())
    setup = client.get("/settings/private-assets?admin_token=setup-secret")
    assert setup.status_code == 200
    assert "Private asset setup" in setup.text

    response = client.post(
        "/settings/private-assets/upload",
        data={"csrf": csrf_token(), "admin_token": "setup-secret"},
        files={
            "resume_pdf": ("resume.pdf", b"%PDF-resume", "application/pdf"),
            "portfolio_pdf": ("portfolio.pdf", b"%PDF-portfolio", "application/pdf"),
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert (private_dir / "arnav_resume.pdf").exists()
    assert (private_dir / "arnav_research_portfolio.pdf").exists()
    assert client.get("/private_assets/arnav_resume.pdf").status_code == 404
    assert client.get("/static/arnav_resume.pdf").status_code == 404


def test_private_asset_setup_rejects_invalid_pdf_upload(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    private_dir = tmp_path / "private_assets"
    settings = get_settings().model_copy(
        update={
            "private_asset_dir": private_dir,
            "resume_pdf_path": private_dir / "arnav_resume.pdf",
            "research_portfolio_pdf_path": private_dir / "arnav_research_portfolio.pdf",
            "admin_setup_token": "setup-secret",
            "project_root": tmp_path,
        },
    )
    monkeypatch.setattr("app.routes.settings.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.assets.get_settings", lambda: settings)

    client = TestClient(create_app())
    response = client.post(
        "/settings/private-assets/upload",
        data={"csrf": csrf_token(), "admin_token": "setup-secret"},
        files={"resume_pdf": ("resume.txt", b"not a pdf", "text/plain")},
    )

    assert response.status_code == 400
    assert not (private_dir / "arnav_resume.pdf").exists()
