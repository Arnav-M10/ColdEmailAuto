from app.observability.logging import REDACTED, redact_mapping


def test_redact_mapping_removes_secret_like_values() -> None:
    payload = {
        "Authorization": "Bearer secret-token",
        "refresh_token": "secret",
        "normal": "kept",
    }

    redacted = redact_mapping(payload)

    assert redacted["Authorization"] == REDACTED
    assert redacted["refresh_token"] == REDACTED
    assert redacted["normal"] == "kept"

