from fastapi.testclient import TestClient

from app.main import create_app


def test_security_headers_are_applied() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "same-origin"
    assert response.headers["X-Request-ID"]

