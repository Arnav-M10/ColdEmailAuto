from typing import Any

import pytest

from app.config import Settings
from app.models.paper import EvidenceClassification
from app.services.ai_providers import (
    AIAuthenticationError,
    AIConfigurationError,
    AIProviderConfig,
    AIProviderError,
    AIResponseError,
    AITimeoutError,
    EvidenceClaim,
    GeminiProvider,
    MockProvider,
    PaperAnalysisOutput,
    PaperAnalysisRequest,
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

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: float,
    ) -> FakeAIResponse:
        del headers, json, timeout
        assert "key=test-key" in url
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


def provider_config(*, retries: int = 0, api_key: str | None = "test-key") -> Settings:
    return Settings(
        ai_provider="gemini",
        ai_model="gemini-test",
        ai_api_key=api_key,
        ai_retries=retries,
        ai_timeout_seconds=1.0,
        ai_temperature=0.0,
        ai_max_tokens=512,
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


def test_missing_gemini_api_key_is_configuration_error() -> None:
    with pytest.raises(AIConfigurationError, match="Gemini API key is missing"):
        get_ai_provider(provider_config(api_key=None))


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


def test_malformed_json_is_rejected() -> None:
    client = FakeAIClient([FakeAIResponse(200, gemini_payload("not json"))])
    provider = GeminiProvider(AIProviderConfig.from_settings(provider_config()), client=client)

    with pytest.raises(AIResponseError, match="malformed JSON"):
        provider.analyze_paper(request())


def test_schema_validation_failure_is_rejected() -> None:
    client = FakeAIClient([FakeAIResponse(200, gemini_payload('{"title": "missing fields"}'))])
    provider = GeminiProvider(AIProviderConfig.from_settings(provider_config()), client=client)

    with pytest.raises(AIResponseError, match="schema validation"):
        provider.analyze_paper(request())


def test_retry_logic_recovers_from_bad_first_response() -> None:
    client = FakeAIClient(
        [
            FakeAIResponse(200, gemini_payload("not json")),
            FakeAIResponse(200, gemini_payload(valid_output_text())),
        ],
    )
    provider = GeminiProvider(
        AIProviderConfig.from_settings(provider_config(retries=1)),
        client=client,
    )

    output = provider.analyze_paper(request())

    assert output.title == "Magnetic structures"
    assert client.calls == 2


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


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(AIProviderError, match="Unsupported AI provider"):
        get_ai_provider(Settings(ai_provider="unknown"))
