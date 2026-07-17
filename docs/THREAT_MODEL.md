# Threat Model

This document tracks security and safety risks for the Professor Outreach Manager.

Initial threats from `PROJECT_SPEC.md`:

- Malicious webpages.
- Malicious PDFs.
- Prompt injection.
- Compromised APIs.
- Accidental mass drafting.
- Duplicate messages.
- Leaked keys or tokens.
- Path traversal.
- SSRF.
- SQL injection.
- XSS.
- CSRF.
- Dependency compromise.
- Accidental deletion.
- Database corruption.
- Identity mismatch.
- Model hallucination.
- Unsupported claims and overclaiming.

Phase 0 controls will focus on project hygiene, local-only defaults, secret exclusion, documentation, and testable no-send policy.

## Phase 0 Controls

- Runtime secrets, local databases, PDFs, logs, and exports are ignored by Git.
- No-send policy is centralized in `app/safety.py` and covered by tests.
- Security headers are applied to every response.
- Request logs use structured JSON and include request ID, method, path, status, and duration.
- Logging redacts fields with names that look like authorization headers, tokens, API keys, secrets, or passwords.
- Request logging records paths only, not request bodies, email bodies, paper text, tokens, or authorization headers.
