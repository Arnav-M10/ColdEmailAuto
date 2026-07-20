from app.observability.logging import REDACTED, redact_mapping


def test_redact_mapping_removes_secret_like_values() -> None:
    payload = {
        "Authorization": "Bearer secret-token",
        "refresh_token": "secret",
        "normal": "kept",
        "headers": {
            "x-goog-api-key": "gemini-secret",
            "Content-Type": "application/json",
        },
        "generationConfig": {"maxOutputTokens": 4096},
    }

    redacted = redact_mapping(payload)

    assert redacted["Authorization"] == REDACTED
    assert redacted["refresh_token"] == REDACTED
    assert redacted["normal"] == "kept"
    assert redacted["headers"]["x-goog-api-key"] == REDACTED
    assert redacted["headers"]["Content-Type"] == "application/json"
    assert redacted["generationConfig"]["maxOutputTokens"] == 4096
