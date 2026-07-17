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
