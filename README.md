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

Use Python 3.12. On this Codex desktop workspace, the bundled Python 3.12 path is:

```bash
/Users/arnav/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
```

Create and activate a local virtual environment:

```bash
/Users/arnav/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Run the local app:

```bash
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

Run checks:

```bash
source .venv/bin/activate
ruff check .
mypy app tests
pytest
bandit -c pyproject.toml -r app
pip-audit --cache-dir /private/tmp/pip-audit-cache
```

Initialize or upgrade the local database with Alembic:

```bash
source .venv/bin/activate
alembic upgrade head
```

The app also creates the Phase 0 SQLite tables automatically on local startup. Runtime database files under `data/` are ignored by Git.

Baseline:

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
