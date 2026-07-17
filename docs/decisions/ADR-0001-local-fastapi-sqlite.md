# ADR-0001: Local FastAPI and SQLite Foundation

## Status

Accepted

## Context

The project is a local, single-user Professor Outreach Manager. It needs to be maintainable, understandable, testable, and safe before later integrations are added.

## Decision

Use Python 3.12, FastAPI, server-rendered pages, SQLite, SQLAlchemy 2.x, Alembic, Pydantic v2, and local filesystem storage for the MVP foundation.

## Consequences

- The system stays simple enough to inspect and run locally.
- There is no cloud infrastructure or multi-user surface in the MVP.
- Later long-running work should use a local job table and worker rather than Celery, Redis, Kafka, or Kubernetes.
- The design remains compatible with future adapters for discovery, retrieval, analysis, drafting, and Outlook drafts.

