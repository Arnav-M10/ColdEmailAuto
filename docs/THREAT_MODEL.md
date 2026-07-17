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

Phase 0 and Phase 1 controls focus on project hygiene, local-only defaults, secret exclusion, documentation, safe local files, auditable manual workflow, and testable no-send policy.

## Phase 0 Controls

- Runtime secrets, local databases, PDFs, logs, and exports are ignored by Git.
- No-send policy is centralized in `app/safety.py` and covered by tests.
- Security headers are applied to every response.
- Request logs use structured JSON and include request ID, method, path, status, and duration.
- Logging redacts fields with names that look like authorization headers, tokens, API keys, secrets, or passwords.
- Request logging records paths only, not request bodies, email bodies, paper text, tokens, or authorization headers.

## Phase 1 Controls

- Candidate and official email records are manually entered with provenance.
- Contact-history CSV import validates rows and skips duplicates.
- PDF upload rejects non-PDF signatures, malformed files, encrypted files, oversized files, and unsafe filenames.
- Uploaded papers and extracted text are stored only in ignored local paths.
- Draft generation requires saved full-paper analysis and evidence.
- Draft approval is blocked when required attachments are missing or invalid.
- Follow-up tracking is limited to one local suggestion and is disabled after explicit decline.
- No Outlook, crawling, metadata API, SMTP, scheduled-send, or browser-send automation exists.

## Phase 2 Controls

- Remote retrieval is allowlist-oriented: official university domains and known public research APIs only.
- URL validation rejects non-HTTPS, localhost, private IPs, link-local ranges, metadata hosts, arbitrary domains, and local-file URLs.
- Hostnames are resolved before retrieval and blocked if any resolved address is private or local.
- Redirect targets are revalidated before following.
- Department import retrieval checks robots policy and has a per-domain delay hook.
- HTML/PDF responses are capped and content-checked before downstream parsing.
- Department import candidates remain previews until explicitly reviewed and saved.
