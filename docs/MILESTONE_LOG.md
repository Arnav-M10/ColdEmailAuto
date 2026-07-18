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

## Phase 2

- Phase 2.1 - safe web retrieval foundation with SSRF blocking, redirect revalidation, robots checks, response caps, and discovery review tables.
- Phase 2.2 - department discovery importer, five-layout extraction coverage, transparent candidate scoring, and review-before-save UI.
- Phase 2.3 - discovery false-positive fix: homepages resolve to an approved faculty directory first, person extraction requires source structure plus supporting signals, source elements are shown for every preview, and MIT Physics homepage navigation/program/news text is covered by regression tests. Live MIT smoke test resolved `https://physics.mit.edu/` to `https://physics.mit.edu/faculty/` and found 108 faculty profiles with no rejected navigation/program labels as names.
- Phase 2.4 - candidate screening and ranking: discovery previews now store inclusion/exclusion status, evidence-based ranking reasons, exclusion reasons, warning reasons, manual override state, and a screening score. The dashboard now reports real local workflow counts instead of placeholder cards.

## Phase 3

- Phase 3.1 - publication metadata tables, OpenAlex/Crossref response normalization, metadata deduplication, author identity review, and paper scoring.
- Phase 3.2 - Publication Memory UI and manual Scholar reconciliation without Scholar scraping.
- Phase 3.3 - live OpenAlex/Crossref publication retrieval with cached API JSON, author identity confidence scoring, manual OpenAlex author-ID confirmation when uncertain, DOI confirmation through Crossref, recent-work retrieval, deduplication, and local provenance timestamps.
- Phase 3.4 - paper selection gate: candidate publication rows now show ranking evidence, authorship position, central-role signal, fit score, full-text availability, and warnings. Publication PDF retrieval and publication-linked analysis are blocked until the user explicitly approves the paper.
- Phase 3.5 - publication workflow repair: `/publications` now shows saved candidates before publications exist, exposes a clear per-candidate `Fetch Publications` action, and has an end-to-end MIT Physics regression covering directory approval, Kevin Burdge save, OpenAlex/Crossref retrieval, persistence, and publication rendering.
- Phase 3.6 - OpenAlex author confirmation: ambiguous author matches now render a normal ranked HTML selection page instead of JSON, store the chosen OpenAlex author ID on the candidate, and retry publication retrieval immediately after confirmation.

## Phase 4

- Phase 4.1 - lawful PDF retrieval foundation with arXiv planning, safe PDF download, and paper source provenance.
- Phase 4.1a - ordered lawful PDF retrieval: approved papers now try arXiv, official university/institutional public PDFs, approved public full-text hosts, and OpenAlex open-access PDF locations in order; failed attempts mark `NO_FULL_TEXT` with DOI/source context, and duplicate same-candidate paper retrieval reuses the stored PDF record.
- Phase 4.1b - provider-based AI architecture: generic `AIProvider` interface, Gemini default provider, future OpenAI boundary without implementation, centralized AI settings, Pydantic output validation, grounded evidence checks, retry/error handling, and missing-key behavior that refuses to create fake analysis.
- Phase 4.2 - rich local paper analysis, text-quality metadata, deterministic evidence extraction, and stricter draft approval gates.

Phase 4.2 checks:

- `ruff check .` passed.
- `mypy app tests scripts` passed.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q` passed, 58 tests. Plugin autoload is disabled to avoid unrelated coverage-plugin startup stalls in this local environment.
- `bandit -c pyproject.toml -r app scripts` passed.
- `python -m scripts.secret_scan` passed.
- `alembic upgrade head` passed.
- `pip-audit --cache-dir /private/tmp/pip-audit-cache` passed with no known vulnerabilities.

## Latest Full Gate Set

- `ruff check .`
- `mypy app tests scripts`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q`
- `bandit -c pyproject.toml -r app scripts`
- `pip-audit --cache-dir /private/tmp/pip-audit-cache`
- `python -m scripts.secret_scan`
