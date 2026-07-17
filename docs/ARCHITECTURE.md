# Architecture

This document describes the local application architecture as implemented through Phase 1.

Initial direction:

- Python 3.12.
- FastAPI.
- Server-rendered Jinja2 pages.
- SQLite for local storage.
- SQLAlchemy 2.x and Alembic for data access and migrations.
- Explicit service boundaries for discovery, retrieval, analysis, drafting, Outlook, audit, and safety policy.

The architecture must preserve the no-send boundary described in `PROJECT_SPEC.md`.

## Phase 0 Application Shell

The application starts as a local FastAPI app with server-rendered Jinja2 templates. The initial pages are:

- Dashboard.
- Health.
- Settings.
- Candidates.
- Papers.
- Drafts.

These pages are placeholders in Phase 0, but the navigation, layout, and safety notices are real.

The no-send policy is centralized in `app/safety.py` and covered by tests. Future Outlook work must depend on this boundary rather than introducing independent mail behavior.

## Database

The Phase 0 database is SQLite at `data/outreach.db` by default. SQLAlchemy owns the model definitions and Alembic owns migrations.

The app creates the foundation tables on local startup so the health check and UI remain easy to run. Alembic migrations remain the durable upgrade path for explicit schema changes.

## Observability and HTTP Safety

Every HTTP response receives a request ID and secure browser headers. Requests are logged as structured JSON with method, path, status code, and duration. Logs must not include request bodies, full email bodies, paper contents, tokens, authorization headers, or API keys.

## Local Profile and Assets

The user profile lives at `data/arnav_profile.yaml`. Required first-contact attachments are expected at:

- `assets/arnav_resume.pdf`
- `assets/arnav_research_portfolio.pdf`

The PDFs are ignored by Git. The app validates their PDF signature, parseability, page count, size, and SHA-256 hash. Hashes are written to ignored local manifest `data/local_asset_manifest.json`.

## Phase 1 Manual Workflow

Phase 1 is intentionally local and manual. A candidate can be entered by hand, official email addresses can be recorded with source provenance, contacted-person CSVs can be imported, and candidate status changes are validated.

Manual PDF uploads are stored under ignored `papers/` paths after signature, size, parseability, encryption, and path-safety checks. Extracted text is cached locally under ignored `data/cache/` paths.

Paper analysis is stored as structured `paper_analyses` plus `evidence_items`. Draft generation uses only saved manual analysis and evidence. Draft approval is local only and remains blocked unless a verified official email exists, wording checks pass, and the required resume and portfolio PDFs are valid.

Follow-up tracking is suggestion-only. Marking a candidate manually sent requires a locally approved draft and creates at most one follow-up task. The app does not generate a follow-up email, schedule sending, track opens, or send anything.

## Phase 2 Safe Retrieval Foundation

External retrieval starts behind `app.services.web_safety`. The service validates allowed URL categories, blocks localhost and private networks, resolves hostnames before requests, revalidates redirect targets, checks robots policy, applies per-domain delay hooks, caps response sizes, and validates expected content type. Discovery imports store review candidates in `department_imports` and `discovery_candidates` before any candidate is saved.

The review schema is intentionally separate from `candidates` so department pages can be parsed, scored, and rejected without polluting the permanent outreach memory.

## Phase 2 Discovery Review UI

The Discovery page accepts one official department URL at a time. Fetched pages are parsed into `DiscoveryCandidate` previews with role category, research summary, active topics, remote feasibility, mentoring likelihood, research overlap, confidence, score, official email, homepage, evidence, and warnings. Candidates can be rejected or saved individually. Saving creates the permanent candidate and verified email only after duplicate checks pass.

## Phase 3 Publication Memory

Publication metadata is normalized into `publications` and linked to candidates through `authorships`. OpenAlex and Crossref clients convert API responses into a shared `PublicationMetadata` shape. Deduplication prefers DOI, arXiv ID, OpenAlex ID, and finally a normalized title fingerprint. Candidate-author identity matching records confidence, review-required states, author position, large-author warnings, and publication fit scoring without treating metadata as unquestionably correct.

Manual Scholar workflows store pasted Scholar URLs only as source context. The app does not scrape Scholar. Users can add or reconcile publication metadata from a candidate page, and ambiguous author matches remain marked for review.

## Phase 4 Retrieval Foundation

Publication PDFs are retrieved only through the safe fetcher. arXiv IDs resolve to `https://arxiv.org/pdf/...`; metadata PDF URLs are used only when present and valid. Downloaded content must pass PDF signature and parser checks before storage. Stored `paper_files` now retain `publication_id`, `source_url`, and `license_note` so every retrieved paper can be traced back to its lawful source.

Phase 4 analysis records text quality metadata for parsed PDFs and expands `paper_analyses` with equations, computational methods, datasets, software, assumptions, limitations, future work, contribution areas, candidate-role notes, and overclaim risks. The local deterministic analyzer only extracts claims from parsed text and creates evidence items; missing details stay marked as unknown rather than inferred.
