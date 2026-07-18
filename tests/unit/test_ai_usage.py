from pathlib import Path

import pytest

from app.config import get_settings
from app.services.ai_usage import (
    AIRequestLimitError,
    assert_ai_request_allowed,
    record_ai_request,
)


def test_ai_usage_daily_and_workflow_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(
        "app.services.ai_usage.get_settings",
        lambda: settings.model_copy(
            update={"ai_daily_request_limit": 2, "ai_max_requests_per_workflow": 1},
        ),
    )
    usage_path = tmp_path / "usage.json"

    assert_ai_request_allowed(workflow_id=7, usage_path=usage_path)
    snapshot = record_ai_request(workflow_id=7, usage_path=usage_path)

    assert snapshot.daily_count == 1
    assert snapshot.workflow_count == 1
    with pytest.raises(AIRequestLimitError, match="per-workflow"):
        assert_ai_request_allowed(workflow_id=7, usage_path=usage_path)


def test_ai_usage_daily_limit_blocks_before_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(
        "app.services.ai_usage.get_settings",
        lambda: settings.model_copy(
            update={"ai_daily_request_limit": 1, "ai_max_requests_per_workflow": 5},
        ),
    )
    usage_path = tmp_path / "usage.json"

    record_ai_request(workflow_id=1, usage_path=usage_path)

    with pytest.raises(AIRequestLimitError, match="daily request limit"):
        assert_ai_request_allowed(workflow_id=2, usage_path=usage_path)
