import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from app.config import get_settings

USAGE_PATH = Path("data/cache/ai_usage.json")


class AIRequestLimitError(ValueError):
    pass


@dataclass(frozen=True)
class AIUsageSnapshot:
    day: str
    daily_count: int
    daily_limit: int
    workflow_count: int
    workflow_limit: int


def assert_ai_request_allowed(
    *,
    workflow_id: int | None,
    usage_path: Path | None = None,
) -> AIUsageSnapshot:
    settings = get_settings()
    state: dict[str, Any] = load_usage_state(usage_path)
    today = date.today().isoformat()
    if state.get("day") != today:
        state = {"day": today, "daily_count": 0, "workflows": {}}
    workflows = workflow_counts(state)
    workflow_key = str(workflow_id or "untracked")
    workflow_count = int(workflows.get(workflow_key, 0))
    daily_count = int(state.get("daily_count", 0))
    snapshot = AIUsageSnapshot(
        day=today,
        daily_count=daily_count,
        daily_limit=settings.ai_daily_request_limit,
        workflow_count=workflow_count,
        workflow_limit=settings.ai_max_requests_per_workflow,
    )
    if daily_count >= settings.ai_daily_request_limit:
        raise AIRequestLimitError(
            "AI daily request limit reached. Increase AI_DAILY_REQUEST_LIMIT only if you are "
            "comfortable with the provider usage."
        )
    if workflow_count >= settings.ai_max_requests_per_workflow:
        raise AIRequestLimitError(
            "AI per-workflow request limit reached. Retry after reviewing cached work or "
            "increase AI_MAX_REQUESTS_PER_WORKFLOW."
        )
    return snapshot


def record_ai_request(
    *,
    workflow_id: int | None,
    usage_path: Path | None = None,
) -> AIUsageSnapshot:
    settings = get_settings()
    state: dict[str, Any] = load_usage_state(usage_path)
    today = date.today().isoformat()
    if state.get("day") != today:
        state = {"day": today, "daily_count": 0, "workflows": {}}
    workflows = workflow_counts(state)
    workflow_key = str(workflow_id or "untracked")
    workflows[workflow_key] = int(workflows.get(workflow_key, 0)) + 1
    state["daily_count"] = int(state.get("daily_count", 0)) + 1
    state["updated_at"] = datetime.now(UTC).isoformat()
    save_usage_state(state, usage_path)
    return AIUsageSnapshot(
        day=today,
        daily_count=int(state["daily_count"]),
        daily_limit=settings.ai_daily_request_limit,
        workflow_count=int(workflows[workflow_key]),
        workflow_limit=settings.ai_max_requests_per_workflow,
    )


def load_usage_state(usage_path: Path | None = None) -> dict[str, Any]:
    path = usage_path or get_settings().project_root / USAGE_PATH
    if not path.exists():
        return {"day": date.today().isoformat(), "daily_count": 0, "workflows": {}}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"day": date.today().isoformat(), "daily_count": 0, "workflows": {}}
    return parsed if isinstance(parsed, dict) else {"day": date.today().isoformat()}


def save_usage_state(state: dict[str, Any], usage_path: Path | None = None) -> None:
    path = usage_path or get_settings().project_root / USAGE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def workflow_counts(state: dict[str, Any]) -> dict[str, int]:
    raw = state.setdefault("workflows", {})
    if not isinstance(raw, dict):
        raw = {}
        state["workflows"] = raw
    normalized = {str(key): int(value) for key, value in raw.items()}
    state["workflows"] = normalized
    return normalized
