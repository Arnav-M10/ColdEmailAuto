# Milestone Log

This log records completed implementation milestones. Detailed behavior changes also appear in `CHANGELOG.md`.

## Phase 0

- `0dfeadf` - repository foundation, MIT license, safety docs, ADR directory, and ignore rules.
- `dba8918` - FastAPI application shell with polished placeholder navigation.
- `24e1c91` - SQLite, SQLAlchemy, Alembic, and foundation tables.
- `aaff104` - structured logging, request IDs, security headers, and no-send observability foundation.
- `0d037b3` - local Arnav profile and required asset validation with ignored hash manifest.
- `4dfa415` - tracked-file secret scanning gate.

## Phase 1

- `a7e7fe0` - manual tracker schema for candidates, emails, papers, analyses, evidence, drafts, outreach events, and follow-up tasks.
- `d3cc67f` - manual candidate tracker, official email provenance, duplicate checks, and contacted CSV preview/import.
- `3076b9d` - safe manual PDF upload, hashing, local storage, and text extraction.
- `8c33686` - manual paper analysis, evidence-backed draft generation, draft review page, and local approval checks.
- `d206bca` - local follow-up calculator and one-follow-up manual tracking workflow.

## Latest Full Gate Set

- `ruff check .`
- `mypy app tests scripts`
- `pytest -q`
- `bandit -c pyproject.toml -r app scripts`
- `pip-audit --cache-dir /private/tmp/pip-audit-cache`
- `python -m scripts.secret_scan`
