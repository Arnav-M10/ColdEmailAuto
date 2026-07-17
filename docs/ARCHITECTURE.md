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

