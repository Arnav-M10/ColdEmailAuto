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
- Provider-based AI analysis architecture with Gemini as the default provider.
- One-button Start Outreach flow that chooses an uncontacted local candidate, resolves high-confidence OpenAlex identity, ranks papers, retrieves lawful PDFs, analyzes the paper, generates the email, runs a second AI review, and shows a copy-ready draft.
- AI-assisted research workflow internals remain available as debugging tools for candidate, publication, paper, and draft inspection.
- Researcher intelligence from recent publication metadata, deterministic topic clusters, email-usefulness scoring, and a manual Outlook copy-review page.
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

## Railway Deployment

Railway installs runtime packages from the root `requirements.txt` in this deployment path.
Keep it aligned with `[project].dependencies` in `pyproject.toml`, including
`uvicorn[standard]`, so production starts with the same runtime packages as local development.

The checked-in `railway.json` uses Railpack and starts the app with:

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Using `python -m uvicorn` keeps startup tied to the installed Python environment even if an
executable shim is not on `PATH`. The FastAPI application object is `app` in `app/main.py`, so
`app.main:app` is the correct import target.

Required private PDFs are intentionally ignored by Git. A Railway deployment built only from the
repository will not have your resume or research portfolio unless you provide them through private
storage. The workflow reports `PORTFOLIO_INPUT_UNAVAILABLE` and pauses as
`WAITING_FOR_PORTFOLIO_INPUT` instead of treating missing portfolio text as a real zero-similarity
score or sending you to manual paper selection.

For Railway:

1. Create a persistent volume.
2. Mount it at `/data`.
3. Set these environment variables:

```bash
DATABASE_URL=sqlite:////data/outreach.db
RUNTIME_DATA_DIR=/data
PRIVATE_ASSET_DIR=/data/private_assets
RESUME_PDF_PATH=/data/private_assets/arnav_resume.pdf
RESEARCH_PORTFOLIO_PDF_PATH=/data/private_assets/arnav_research_portfolio.pdf
ADMIN_SETUP_TOKEN=use-a-long-random-secret
```

Use four slashes in `sqlite:////data/outreach.db`. The three-slash form
`sqlite:///data/outreach.db` is relative and can place the database inside the ephemeral deploy
filesystem instead of the mounted Railway volume.

4. Deploy the app.
5. Open Settings, then the private asset setup page with your setup token:
   `/settings/private-assets?admin_token=use-a-long-random-secret`
6. Upload `arnav_resume.pdf` and `arnav_research_portfolio.pdf`.
7. Confirm both files and portfolio text show as available.
8. Return to the candidate and click `Resume Workflow` if a run was waiting for portfolio input.

The private PDFs are stored outside `/static` and are not exposed through a public file route.

Validate required local assets and refresh their ignored hash manifest:

```bash
source .venv/bin/activate
python -m scripts.refresh_asset_manifest
```

## Gemini AI Setup

The default AI provider is Gemini. The rest of the application talks only to the generic provider interface, so future providers can be added without changing candidate, paper, draft, or route logic.

To configure Gemini:

1. Go to [Google AI Studio](https://ai.google.dev/aistudio).
2. Sign in and open the API keys page.
3. Create a Gemini API key. New keys in AI Studio are auth keys by default; restrict older standard keys to the Gemini API if AI Studio marks them unrestricted.
4. Add the key to a local ignored `.env` file:

```bash
AI_PROVIDER=gemini
AI_MODEL=gemini-3.5-flash
GEMINI_API_KEY=your_key_here
AI_TIMEOUT_SECONDS=30
AI_RETRIES=2
AI_TEMPERATURE=0.1
AI_MAX_TOKENS=4096
AI_DAILY_REQUEST_LIMIT=25
AI_MAX_REQUESTS_PER_WORKFLOW=4
AI_REQUIRE_FREE_TIER=true
AUTO_SELECT_PAPER=true
```

`.env` is ignored by Git. Do not commit API keys, logs containing keys, or copied provider responses with private paper text.

If you previously configured `AI_MODEL=gemini-2.5-flash`, update it to `gemini-3.5-flash`.
The provider maps that old app default to the current model for compatibility, but keeping the
environment variable current avoids confusion in logs. The Gemini provider uses the current
`v1beta` `generateContent` REST endpoint and sends the API key in the `x-goog-api-key` header.
An unavailable or misspelled model will produce a clear model-not-found error instead of a
generic HTTP 404.

If `GEMINI_API_KEY` or `AI_API_KEY` is missing, the app will show a clear setup error and will not create an analysis. It never silently falls back to a mock provider.

## Research Workflow

Use `Start Outreach` from the first screen for the normal workflow. The agent chooses the best uncontacted candidate from saved candidates or screened discovery previews, auto-confirms OpenAlex only when confidence is high, retrieves and ranks publications, tries lawful PDFs in ranked order, analyzes the selected paper, writes the email, runs a second AI review, and opens a copy-ready draft page.

The older candidate, publication, paper, and discovery pages are retained under Debug tools for inspection and repair. They are no longer the normal path.

Opening a candidate and using `Run Research Workflow` is still available for debugging a specific candidate. It uses the same safe internals as Start Outreach.

Fetching publications is separate from running the research workflow. Importing or confirming
OpenAlex publications should not create a workflow run unless it is resuming an explicit workflow
that is waiting for author confirmation.

PDF eligibility is determined by one canonical retrieval service and shared by ranking, UI labels,
automatic selection, and PDF retrieval. The workflow distinguishes direct PDF URLs, arXiv-derived
PDF URLs, landing-page-only records, DOI-only records, repository records without PDFs, unsafe URLs,
and missing full-text sources.

If the top-ranked suitable paper fails PDF retrieval, the workflow records the exact safe failure
reason and automatically tries the next suitable paper. Manual publication selection appears only
after all suitable automatic candidates are exhausted or when you explicitly choose a different
paper.

Use `Choose a different paper` when you want a manual override. Manual publication-linked PDF retrieval still requires explicit paper approval.

The final review page is designed for manual copying into school Outlook. It shows copy buttons for the recipient, subject, body, and complete email, but it does not open Outlook, access a mailbox, request mail permissions, or send email.

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
