import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

SECRET_FIELD_MARKERS = ("authorization", "token", "secret", "password", "api_key", "apikey")
REDACTED = "[REDACTED]"


def redact_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in values.items():
        lowered = key.lower()
        if any(marker in lowered for marker in SECRET_FIELD_MARKERS):
            redacted[key] = REDACTED
        else:
            redacted[key] = value
    return redacted


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }

        for attribute in ("request_id", "path", "method", "status_code", "duration_ms"):
            if hasattr(record, attribute):
                payload[attribute] = getattr(record, attribute)

        return json.dumps(redact_mapping(payload), separators=(",", ":"))


def configure_logging(level: int = logging.INFO) -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    has_handler = any(
        getattr(handler, "_professor_outreach_handler", False)
        for handler in root_logger.handlers
    )
    if has_handler:
        return

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler._professor_outreach_handler = True  # type: ignore[attr-defined]
    root_logger.addHandler(handler)
