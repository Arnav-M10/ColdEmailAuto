from app import safety


def test_no_send_policy_is_locked() -> None:
    assert safety.AUTOMATIC_SENDING_ALLOWED is False
    assert safety.DRAFTS_ONLY_MODE_REQUIRED is True
    assert "Mail.Send" in safety.FORBIDDEN_MICROSOFT_GRAPH_SCOPES
    assert "smtp" in safety.FORBIDDEN_EMAIL_TRANSPORTS
    safety.assert_no_send_capability()

