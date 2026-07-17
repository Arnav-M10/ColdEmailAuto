import hmac

from app.config import get_settings


def csrf_token() -> str:
    settings = get_settings()
    return hmac.new(
        settings.csrf_secret.encode("utf-8"),
        b"professor-outreach-local-form",
        "sha256",
    ).hexdigest()


def validate_csrf_token(token: str) -> None:
    if not hmac.compare_digest(token, csrf_token()):
        raise ValueError("Invalid CSRF token.")

