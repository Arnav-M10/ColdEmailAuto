import logging
from typing import Any, cast

import pytest

from app.config import Settings
from app.services.ai_providers import (
    AIAuthenticationError,
    AIConfigurationError,
    AIProviderConfig,
    AIProviderError,
    AIRateLimitError,
    AIResponseError,
    AITimeoutError,
    DraftReviewRequest,
    DraftRevisionRequest,
    EvidenceClaim,
    EvidenceClassification,
    GeminiProvider,
    MockProvider,
    PaperAnalysisOutput,
    PaperAnalysisRequest,
    current_gemini_model_name,
    gemini_model_resource_name,
    get_ai_provider,
)


class FakeAIResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self.payload = payload

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeAIClient:
    def __init__(
        self,
        responses: list[FakeAIResponse] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.responses = responses or []
        self.error = error
        self.calls = 0
        self.requests: list[dict[str, Any]] = []

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: float,
    ) -> FakeAIResponse:
        self.requests.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            },
        )
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


def provider_config(*, retries: int = 0, api_key: str | None = "test-key") -> Settings:
    return Settings.model_validate(
        {
            "ai_provider": "gemini",
            "ai_model": "gemini-test",
            "ai_api_key": api_key,
            "gemini_api_key": None,
            "ai_retries": retries,
            "ai_timeout_seconds": 1.0,
            "ai_temperature": 0.0,
            "ai_max_tokens": 512,
        },
    )


def request() -> PaperAnalysisRequest:
    return PaperAnalysisRequest(
        paper_title="Magnetic structures",
        paper_text="--- Page 1 --- We use numerical simulation to test magnetic structures.",
        profile_summary="Arnav uses scientific Python.",
        connection_context="Parker Solar Probe analysis",
    )


def valid_output_text() -> str:
    return """
    {
      "title": "Magnetic structures",
      "research_question": "How do magnetic structures change?",
      "motivation": "Understand magnetic structure.",
      "methods": "The paper uses numerical simulation.",
      "equations": null,
      "computational_methods": "numerical simulation",
      "datasets": null,
      "software": null,
      "numerical_methods": "simulation",
      "assumptions": null,
      "results": "The paper reports magnetic structures.",
      "limitations": "Limited extracted context.",
      "future_work": "Compare more cases.",
      "contribution_areas": "Python checks",
      "candidate_role_notes": "Role needs manual review.",
      "overclaim_risks": "Do not claim reproduction.",
      "connection_to_arnav": "Parker Solar Probe analysis",
      "confidence": 0.82,
      "evidence": [
        {
          "claim": "The paper uses numerical simulation.",
          "evidence_text": "We use numerical simulation to test magnetic structures.",
          "page_number": 1,
          "section_name": "Extracted text",
          "classification": "EXPLICIT",
          "confidence": 0.9
        }
      ]
    }
    """


def gemini_payload(text: str) -> dict[str, Any]:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def valid_review_text() -> str:
    return """
    {
      "hallucination_check_passed": true,
      "accuracy_check_passed": true,
      "naturalness_check_passed": true,
      "concise": true,
      "overall_passed": true,
      "summary": "The draft is grounded and natural.",
      "concerns": [],
      "suggested_edits": [],
      "confidence": 0.91
    }
    """


def valid_revision_text() -> str:
    body_text = (
        "Dear Professor Doe,\\n\\n"
        "I was mainly intrigued by the numerical checks.\\n\\n"
        "Sincerely,\\n"
        "Arnav Mittal"
    )
    return f"""
    {{
      "subject": "Research inquiry - Magnetic structures",
      "body_text": "{body_text}",
      "revision_notes": "Removed unsupported wording and kept the note concise.",
      "confidence": 0.88
    }}
    """


def draft_review_request() -> DraftReviewRequest:
    return DraftReviewRequest(
        recipient_name="Professor Jane Doe",
        paper_title="Magnetic structures",
        draft_subject="Research inquiry - Magnetic structures",
        draft_body="Dear Professor Doe,\n\nI was mainly intrigued by the numerical checks.",
        evidence_summary="- numerical checks | page 1 | We use numerical simulation.",
        deterministic_checks=[
            {
                "sentence": "I was mainly intrigued by the numerical checks.",
                "classification": "SUPPORTED",
                "reason": "Grounded in evidence.",
            },
        ],
    )


def draft_revision_request() -> DraftRevisionRequest:
    return DraftRevisionRequest(
        recipient_name="Professor Jane Doe",
        paper_title="Magnetic structures",
        draft_subject="Research inquiry - Magnetic structures",
        draft_body="Dear Professor Doe,\n\nThis robust work is fascinating.",
        evidence_summary="- numerical checks | page 1 | We use numerical simulation.",
        deterministic_checks=[
            {
                "sentence": "This robust work is fascinating.",
                "classification": "UNSUPPORTED",
                "reason": "No matching saved evidence was found.",
            },
        ],
        reviewer_feedback="Remove forbidden wording and unsupported praise.",
        attempt_number=1,
    )


def test_missing_gemini_api_key_is_configuration_error() -> None:
    with pytest.raises(AIConfigurationError, match="Gemini API key is missing"):
        get_ai_provider(provider_config(api_key=None))


def test_gemini_uses_current_official_rest_request_shape() -> None:
    client = FakeAIClient([FakeAIResponse(200, gemini_payload(valid_output_text()))])
    provider = GeminiProvider(
        AIProviderConfig.from_settings(
            Settings(
                ai_provider="gemini",
                ai_model="gemini-3.5-flash",
                ai_api_key="test-key",
                ai_timeout_seconds=12.0,
                ai_temperature=0.1,
                ai_max_tokens=1024,
            ),
        ),
        client=client,
    )

    provider.analyze_paper(request())

    sent = client.requests[0]
    assert (
        sent["url"]
        == "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent"
    )
    assert sent["headers"] == {
        "Content-Type": "application/json",
        "x-goog-api-key": "test-key",
    }
    assert "key=test-key" not in sent["url"]
    generation_config = sent["json"]["generationConfig"]
    assert generation_config["temperature"] == 0.1
    assert generation_config["maxOutputTokens"] == 1024
    assert "responseMimeType" not in generation_config
    assert "responseSchema" not in generation_config
    response_format = generation_config["responseFormat"]["text"]
    assert response_format["mimeType"] == "APPLICATION_JSON"
    assert response_format["schema"]["type"] == "object"
    assert response_format["schema"]["properties"]["evidence"]["type"] == "array"
    assert "contents" in sent["json"]
    assert "systemInstruction" in sent["json"]
    assert sent["timeout"] == 12.0


def test_gemini_logs_request_and_response_without_api_key(caplog: pytest.LogCaptureFixture) -> None:
    client = FakeAIClient([FakeAIResponse(200, gemini_payload(valid_output_text()))])
    provider = GeminiProvider(AIProviderConfig.from_settings(provider_config()), client=client)

    with caplog.at_level(logging.INFO, logger="professor_outreach.ai"):
        provider.analyze_paper(request())

    messages = [record.__dict__ for record in caplog.records]
    request_record = next(record for record in messages if record["msg"] == "gemini_request")
    response_record = next(record for record in messages if record["msg"] == "gemini_response")
    assert request_record["headers"]["x-goog-api-key"] == "<redacted>"
    assert "test-key" not in str(request_record)
    assert response_record["status_code"] == 200
    assert "candidates" in response_record["payload"]


def test_gemini_reviews_draft_with_structured_payload() -> None:
    client = FakeAIClient([FakeAIResponse(200, gemini_payload(valid_review_text()))])
    provider = GeminiProvider(AIProviderConfig.from_settings(provider_config()), client=client)

    review = provider.review_draft(draft_review_request())

    sent = client.requests[0]
    assert review.overall_passed is True
    assert provider.model == "gemini-test"
    assert sent["url"].endswith("/models/gemini-test:generateContent")
    assert "second reviewer" in sent["json"]["systemInstruction"]["parts"][0]["text"]
    response_schema = sent["json"]["generationConfig"]["responseFormat"]["text"]["schema"]
    assert response_schema["properties"]["overall_passed"] == {"type": "boolean"}


def test_gemini_revises_draft_with_structured_payload() -> None:
    client = FakeAIClient([FakeAIResponse(200, gemini_payload(valid_revision_text()))])
    provider = GeminiProvider(AIProviderConfig.from_settings(provider_config()), client=client)

    revision = provider.revise_draft(draft_revision_request())

    sent = client.requests[0]
    assert revision.subject == "Research inquiry - Magnetic structures"
    assert "Remove forbidden wording" in sent["json"]["contents"][0]["parts"][0]["text"]
    response_schema = sent["json"]["generationConfig"]["responseFormat"]["text"]["schema"]
    assert response_schema["properties"]["body_text"] == {"type": "string"}
    assert sent["json"]["generationConfig"]["responseFormat"]["text"]["mimeType"] == (
        "APPLICATION_JSON"
    )


def test_gemini_accepts_official_model_resource_names() -> None:
    assert gemini_model_resource_name("gemini-3.5-flash") == "models/gemini-3.5-flash"
    assert gemini_model_resource_name("models/gemini-3.5-flash") == "models/gemini-3.5-flash"


def test_legacy_configured_gemini_model_uses_current_model() -> None:
    assert current_gemini_model_name("gemini-2.5-flash") == "gemini-3.5-flash"
    assert current_gemini_model_name("models/gemini-2.5-flash") == "models/gemini-3.5-flash"


def test_default_gemini_model_matches_current_docs() -> None:
    assert Settings.model_fields["ai_model"].default == "gemini-3.5-flash"


def test_gemini_404_names_the_configured_model() -> None:
    client = FakeAIClient([FakeAIResponse(404, {})])
    provider = GeminiProvider(AIProviderConfig.from_settings(provider_config()), client=client)

    with pytest.raises(AIProviderError, match="gemini-test"):
        provider.analyze_paper(request())


def test_invalid_gemini_api_key_is_reported() -> None:
    client = FakeAIClient([FakeAIResponse(403, {})])
    provider = GeminiProvider(AIProviderConfig.from_settings(provider_config()), client=client)

    with pytest.raises(AIAuthenticationError, match="rejected"):
        provider.analyze_paper(request())

    assert client.calls == 1


def test_gemini_timeout_is_reported() -> None:
    client = FakeAIClient(error=TimeoutError())
    provider = GeminiProvider(AIProviderConfig.from_settings(provider_config()), client=client)

    with pytest.raises(AITimeoutError, match="timed out"):
        provider.analyze_paper(request())


def test_malformed_json_is_rejected_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = FakeAIClient([FakeAIResponse(200, gemini_payload("not json"))])
    provider = GeminiProvider(AIProviderConfig.from_settings(provider_config()), client=client)

    with caplog.at_level(logging.INFO, logger="professor_outreach.ai"):
        with pytest.raises(AIResponseError, match="paper_analysis"):
            provider.analyze_paper(request())

    raw_record = next(record for record in caplog.records if record.msg == "ai_raw_response")
    raw_record_extra = cast(Any, raw_record)
    assert raw_record_extra.call_name == "paper_analysis"
    assert raw_record_extra.payload["raw_text"] == "not json"


def test_common_json_formatting_issues_are_repaired(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fenced = (
        "Here is the JSON.\n```json\n"
        + valid_output_text().replace(
            '"confidence": 0.9\n        }',
            '"confidence": 0.9,\n        }',
        )
        + "\n```\nDone."
    )
    client = FakeAIClient([FakeAIResponse(200, gemini_payload(fenced))])
    provider = GeminiProvider(AIProviderConfig.from_settings(provider_config()), client=client)

    with caplog.at_level(logging.INFO, logger="professor_outreach.ai"):
        output = provider.analyze_paper(request())

    assert output.title == "Magnetic structures"
    repair_records = [
        record for record in caplog.records if record.msg == "ai_json_repair_applied"
    ]
    assert repair_records
    repair_record_extra = cast(Any, repair_records[-1])
    assert repair_record_extra.call_name == "paper_analysis"


def test_schema_validation_failure_is_rejected() -> None:
    client = FakeAIClient([FakeAIResponse(200, gemini_payload('{"title": "missing fields"}'))])
    provider = GeminiProvider(AIProviderConfig.from_settings(provider_config()), client=client)

    with pytest.raises(AIResponseError, match="schema validation"):
        provider.analyze_paper(request())


def test_retry_logic_recovers_from_bad_first_response(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeAIClient(
        [
            FakeAIResponse(200, gemini_payload("not json")),
            FakeAIResponse(200, gemini_payload(valid_output_text())),
        ],
    )
    monkeypatch.setattr("app.services.ai_providers.time.sleep", lambda delay: None)
    provider = GeminiProvider(
        AIProviderConfig.from_settings(provider_config(retries=1)),
        client=client,
    )

    output = provider.analyze_paper(request())

    assert output.title == "Magnetic structures"
    assert client.calls == 2


def test_gemini_429_retries_with_exponential_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays: list[float] = []
    client = FakeAIClient(
        [
            FakeAIResponse(429, {"error": {"message": "rate limit"}}),
            FakeAIResponse(200, gemini_payload(valid_output_text())),
        ],
    )
    monkeypatch.setattr("app.services.ai_providers.time.sleep", delays.append)
    provider = GeminiProvider(
        AIProviderConfig.from_settings(provider_config(retries=1)),
        client=client,
    )

    output = provider.analyze_paper(request())

    assert output.title == "Magnetic structures"
    assert client.calls == 2
    assert delays == [1.0]


def test_gemini_persistent_429_raises_rate_limit_after_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays: list[float] = []
    client = FakeAIClient(
        [
            FakeAIResponse(429, {"error": {"message": "rate limit one"}}),
            FakeAIResponse(429, {"error": {"message": "rate limit two"}}),
            FakeAIResponse(429, {"error": {"message": "rate limit three"}}),
        ],
    )
    monkeypatch.setattr("app.services.ai_providers.time.sleep", delays.append)
    provider = GeminiProvider(
        AIProviderConfig.from_settings(provider_config(retries=2)),
        client=client,
    )

    with pytest.raises(AIRateLimitError, match="HTTP 429"):
        provider.analyze_paper(request())

    assert client.calls == 3
    assert delays == [1.0, 2.0]


def test_evidence_must_be_grounded_in_paper_text() -> None:
    ungrounded = valid_output_text().replace(
        "We use numerical simulation to test magnetic structures.",
        "This excerpt is not in the paper.",
    )
    client = FakeAIClient([FakeAIResponse(200, gemini_payload(ungrounded))])
    provider = GeminiProvider(AIProviderConfig.from_settings(provider_config()), client=client)

    with pytest.raises(AIResponseError, match="does not appear"):
        provider.analyze_paper(request())


def test_provider_selection_and_switching() -> None:
    gemini = get_ai_provider(provider_config(), client=FakeAIClient())
    openai = get_ai_provider(Settings(ai_provider="openai", ai_model="future-model"))
    mock = MockProvider(
        PaperAnalysisOutput(
            title="Mock",
            research_question="Question",
            motivation="Motivation",
            methods="Methods",
            results="Results",
            overclaim_risks="Risk",
            connection_to_arnav="Connection",
            confidence=0.8,
            evidence=[
                EvidenceClaim(
                    claim="Claim",
                    evidence_text="Evidence",
                    page_number=1,
                    section_name="Section",
                    classification=EvidenceClassification.EXPLICIT,
                    confidence=0.8,
                ),
            ],
        ),
    )

    assert gemini.name == "gemini"
    assert openai.name == "openai"
    assert mock.analyze_paper(request()).title == "Mock"
    assert mock.review_draft(draft_review_request()).overall_passed is True
    revision_request = draft_revision_request()
    assert mock.revise_draft(revision_request).subject == revision_request.draft_subject


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(AIProviderError, match="Unsupported AI provider"):
        get_ai_provider(Settings(ai_provider="unknown"))
