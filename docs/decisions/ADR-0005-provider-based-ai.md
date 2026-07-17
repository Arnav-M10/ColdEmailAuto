# ADR-0005: Provider-Based AI Analysis

## Status

Accepted.

## Context

Paper analysis needs a real AI provider, but the outreach workflow must not become coupled to one vendor or silently fall back to fake output. Provider calls also handle sensitive parsed paper text, so prompt-injection resistance, minimal context, structured validation, and explicit failure behavior are safety requirements.

## Decision

All provider-backed analysis goes through a generic `AIProvider` interface. Gemini is the first real provider and the default runtime provider. OpenAI is represented only as a future provider boundary; it is not implemented yet. Test mocks are injectable into services but cannot be selected from runtime settings.

Provider configuration is centralized in settings: provider, model, API key, timeout, retries, temperature, and max tokens. Gemini-specific request and response logic stays inside `GeminiProvider`.

Provider output must be JSON validated by Pydantic before persistence. Evidence excerpts must appear in the parsed paper text, at least one `EXPLICIT` evidence item is required, and missing keys, invalid keys, timeouts, malformed JSON, and schema failures must not create analysis rows.

## Consequences

- Candidate, publication, paper, and draft workflow code does not depend directly on Gemini.
- Adding OpenAI or another provider later should require a provider implementation and configuration, not route or workflow rewrites.
- Missing provider credentials produce clear setup errors instead of crashes or fake analysis.
- Provider-backed analysis remains compatible with the existing no-send boundary and later Outlook draft-only integration.
