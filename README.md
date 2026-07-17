# Professor Outreach Manager

A local, human-supervised application for careful, paper-first professor outreach.

This project is governed by `PROJECT_SPEC.md`. Safety, truthfulness, privacy, and human approval override convenience and feature speed.

## Current Status

Phases 0-4 are implemented as a local, safe research-assistant workflow.

Implemented so far:

- Repository safety documentation and ADRs.
- MIT license.
- Git ignore rules for local secrets, databases, logs, PDFs, exports, and generated files.
- FastAPI/Jinja desktop-style local web app.
- SQLite database with SQLAlchemy models and Alembic migrations.
- Local Arnav profile loading and required PDF attachment validation.
- Candidate CRUD, official email provenance, duplicate checks, and contacted-person CSV import.
- Manual lawful PDF upload with validation, hashing, safe storage, and text extraction.
- Manual paper analysis with evidence records.
- Conservative local draft generation and approval checks.
- Follow-up calculator and one-follow-up manual tracker.
- One-URL-at-a-time official department discovery with review-before-save previews.
- Safe web retrieval with SSRF blocking, robots checks, redirect validation, and response caps.
- Publication memory with OpenAlex/Crossref normalization, manual Scholar reconciliation, deduplication, author identity review, and paper scoring.
- Lawful PDF retrieval through the safe fetcher, including arXiv PDF planning and source provenance.
- Rich local paper analysis fields, text-quality metadata, deterministic evidence extraction, and stricter draft approval gates.
- Structured logging, request IDs, security headers, secret scan, dependency audit, and no-send regression tests.

Not implemented yet:

- Live whole-web crawling or automatic Google Scholar scraping.
- Outlook draft creation.
- Reply classification.
- Background workers.

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

The initial local profile is stored at `data/arnav_profile.yaml`. Treat it as local personal data even when it contains only basic information.

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
mypy app tests scripts
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q
bandit -c pyproject.toml -r app scripts
pip-audit --cache-dir /private/tmp/pip-audit-cache
python -m scripts.secret_scan
```

Initialize or upgrade the local database with Alembic:

```bash
source .venv/bin/activate
alembic upgrade head
```

The app also creates the Phase 0 SQLite tables automatically on local startup. Runtime database files under `data/` are ignored by Git.

Logs are structured JSON and are intended for local troubleshooting. Do not paste logs into public systems without reviewing them for private data.

Validate required local assets and refresh their ignored hash manifest:

```bash
source .venv/bin/activate
python -m scripts.refresh_asset_manifest
```

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
