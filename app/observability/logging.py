import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

SECRET_FIELD_MARKERS = (
    "authorization",
    "secret",
    "password",
    "api_key",
    "api-key",
    "apikey",
)
REDACTED = "[REDACTED]"
LOG_EXTRA_ATTRIBUTES = (
    "request_id",
    "path",
    "method",
    "status_code",
    "duration_ms",
    "url",
    "headers",
    "payload",
    "candidate_id",
    "draft_id",
    "workflow_id",
    "reason",
)


def redact_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in values.items():
        if is_secret_key(key):
            redacted[key] = REDACTED
        else:
            redacted[key] = redact_value(value)
    return redacted


def is_secret_key(key: str) -> bool:
    lowered = key.lower()
    normalized = lowered.replace("-", "_")
    return (
        any(marker in lowered for marker in SECRET_FIELD_MARKERS)
        or normalized == "token"
        or normalized.endswith("_token")
    )


def redact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return redact_mapping(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }

        for attribute in LOG_EXTRA_ATTRIBUTES:
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
