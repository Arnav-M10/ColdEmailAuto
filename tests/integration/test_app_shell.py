from fastapi.testclient import TestClient

from app.main import create_app


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


def test_settings_page_shows_required_assets() -> None:
    client = TestClient(create_app())

    response = client.get("/settings")

    assert response.status_code == 200
    assert "Required assets" in response.text
    assert "assets/arnav_resume.pdf" in response.text
    assert "assets/arnav_research_portfolio.pdf" in response.text
