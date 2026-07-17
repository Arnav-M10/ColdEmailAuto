# Architecture

This document will describe the local application architecture as Phase 0 implementation proceeds.

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
