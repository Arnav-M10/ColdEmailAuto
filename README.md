# Professor Outreach Manager

A local, human-supervised application for careful, paper-first professor outreach.

This project is governed by `PROJECT_SPEC.md`. Safety, truthfulness, privacy, and human approval override convenience and feature speed.

## Current Status

Phase 0 is in progress. The repository foundation is being created before application code is added.

Implemented so far:

- Repository safety documentation.
- MIT license.
- Git ignore rules for local secrets, databases, logs, PDFs, exports, and generated files.
- Architecture and safety decision records.
- Documentation skeleton for future setup and usage instructions.

Not implemented yet:

- FastAPI application shell.
- Database initialization.
- Candidate tracking.
- Paper upload or parsing.
- Draft generation.
- Outlook draft creation.
- Any external integrations.

## Non-Negotiable Safety Boundary

This application must never send email automatically.

The project must not implement:

- Microsoft Graph `Mail.Send`.
- SMTP sending.
- A send endpoint.
- A hidden or disabled send button.
- Scheduled send.
- Browser automation that presses Send.
- Any indirect workaround that sends mail.

The intended final behavior is to create a reviewable Outlook draft only after explicit user approval.

## Personal Data Notice

The application is designed for local use and may store personal profile data, contact history, local PDFs, draft metadata, and outreach audit records under the project directory.

If this repository is ever made public, do not commit personal profile data, real local databases, resumes, research portfolios, downloaded papers, logs, token caches, exports, or `.env` files. Review `PROJECT_SPEC.md`, `.gitignore`, and `SECURITY.md` before publishing.

## Setup

Exact copy-pastable setup commands will be added during Phase 0 after the Python project configuration and application shell are created.

Planned baseline:

- Python 3.12.
- FastAPI.
- SQLite.
- SQLAlchemy 2.x.
- Alembic.
- Pydantic v2.
- pytest.
- Ruff.
- mypy.
- Bandit.
- Dependency and secret scanning.

## Development Process

Before coding, read `PROJECT_SPEC.md`.

For every milestone:

- Keep changes small.
- Run relevant checks.
- Review the diff.
- Commit only coherent work.
- Update documentation when behavior or safety posture changes.

## License

MIT. See `LICENSE`.

