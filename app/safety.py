"""Central safety policy constants.

These values are intentionally simple and testable. Later integrations must depend on this
module rather than duplicating or weakening the no-send policy.
"""

AUTOMATIC_SENDING_ALLOWED = False
DRAFTS_ONLY_MODE_REQUIRED = True
FORBIDDEN_MICROSOFT_GRAPH_SCOPES = frozenset({"Mail.Send"})
FORBIDDEN_EMAIL_TRANSPORTS = frozenset({"smtp", "scheduled_send", "browser_send_automation"})


def assert_no_send_capability() -> None:
    """Raise if a future edit weakens the project no-send boundary."""

    if AUTOMATIC_SENDING_ALLOWED:
        raise RuntimeError("Automatic email sending is forbidden.")
    if not DRAFTS_ONLY_MODE_REQUIRED:
        raise RuntimeError("Drafts-only mode is required.")
    if "Mail.Send" not in FORBIDDEN_MICROSOFT_GRAPH_SCOPES:
        raise RuntimeError("Mail.Send must remain forbidden.")

