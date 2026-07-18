from app import safety


def test_no_send_policy_is_locked() -> None:
    assert safety.AUTOMATIC_SENDING_ALLOWED is False
    assert safety.DRAFTS_ONLY_MODE_REQUIRED is True
    assert "Mail.Send" in safety.FORBIDDEN_MICROSOFT_GRAPH_SCOPES
    assert "smtp" in safety.FORBIDDEN_EMAIL_TRANSPORTS
    safety.assert_no_send_capability()


def test_no_mailbox_integration_routes_exist() -> None:
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    route_text = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in (project_root / "app/routes").glob("**/*")
        if path.is_file() and path.suffix == ".py"
    )
    ui_text = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for folder in ["app/templates", "app/static"]
        for path in (project_root / folder).glob("**/*")
        if path.is_file() and path.suffix in {".html", ".js"}
    )

    assert "graph.microsoft" not in route_text + ui_text
    assert "gmail" not in route_text + ui_text
    assert "mail.send" not in route_text
    assert "smtp" not in route_text
