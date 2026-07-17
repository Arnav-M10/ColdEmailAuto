# User Guide

The user guide will be expanded as application features are implemented.

Phase 0 will provide only a local application shell and foundation checks.

## Phase 0 Asset Setup

Place the required files at:

- `assets/arnav_resume.pdf`
- `assets/arnav_research_portfolio.pdf`

Then run:

```bash
source .venv/bin/activate
python -m scripts.refresh_asset_manifest
```

The Settings page shows whether both required PDFs are valid. Later draft approval and Outlook draft creation must remain blocked when either file is missing or invalid.

## Phase 1 Manual Candidates

Use Candidates to add one researcher at a time. Record only official email addresses and include the source URL. Candidate status changes are validated so draft readiness cannot be reached before paper analysis.

Use History to preview a contacted-person CSV. CSV preview validates rows before import work is expanded.

## Phase 1 Manual Papers

Open a candidate and upload a lawful PDF manually. The app validates the PDF signature, rejects encrypted or malformed files, stores the file under `papers/`, records its SHA-256 hash, and extracts text to ignored local cache for later analysis.

## Phase 1 Manual Analysis and Drafts

Open a paper, enter a manual analysis, and include at least one evidence-backed claim. Draft generation uses that evidence and Arnav's local profile. Draft approval is local only and is blocked unless a verified official email exists and the required resume and portfolio PDFs are valid.

Later phases will document:

- Profile setup.
- Asset configuration.
- Candidate tracking.
- Manual paper upload.
- Paper analysis review.
- Draft review.
- Outlook draft creation.
- Follow-up tracking.
