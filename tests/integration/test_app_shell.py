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
    assert "assets/arnav_resume.pdf" in response.text
    assert "assets/arnav_research_portfolio.pdf" in response.text
