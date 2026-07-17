# Changelog

All notable project changes will be documented here.

## Unreleased

### Added

- Repository foundation documentation.
- MIT license.
- Safety-focused contributor guidance in `AGENTS.md`.
- Architecture and safety ADR directory.
- Initial documentation skeleton.
- Python 3.12 project configuration.
- FastAPI application shell with placeholder pages.
- Initial no-send regression test.
- SQLite database foundation with SQLAlchemy and Alembic.
- Structured request logging, redaction helpers, request IDs, and secure headers.
- Local profile YAML, required asset validation, and ignored asset hash manifest.
- Tracked-file secret scanning command and configuration.
- Phase 1 manual tracker schema and candidate status transition validation.
- Manual candidate CRUD, official email provenance, duplicate checks, and contacted CSV preview.
- Safe manual PDF upload, hashing, storage, and text extraction.
- Manual paper analysis, evidence entry, conservative draft generation, and local draft approval checks.
- Local follow-up calculator and one-follow-up manual tracking workflow.
- Phase 2 safe web retrieval foundation with SSRF blocking, robots checks, response caps, and discovery review tables.
- Department discovery importer, five-layout extraction tests, transparent scoring, and review-before-save UI.
- Publication metadata memory with OpenAlex/Crossref normalization, deduplication, author identity checks, and paper scoring.
- Publication Memory UI and manual Scholar reconciliation workflow without Scholar scraping.
- Explicit publication selection gate before PDF retrieval or publication-linked analysis.
- Lawful PDF retrieval foundation with arXiv URL planning, safe PDF download, and paper source provenance.
- Ordered lawful PDF retrieval fallback with approved public full-text host allowlist and duplicate-safe paper storage.
- Rich local paper analysis fields, text-quality metadata, deterministic evidence extraction, and stricter draft approval gates.
