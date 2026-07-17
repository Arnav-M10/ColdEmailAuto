# User Guide

The user guide will be expanded as application features are implemented.

The current app supports local candidate tracking, official department discovery, publication memory, lawful PDF retrieval, paper analysis, local draft review, and follow-up suggestions.

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

## Phase 1 Follow-Up Tracking

After you manually send an approved draft outside this app, open the candidate and mark it sent. The app suggests one follow-up date 8 business days later. Follow-ups are suggestions only; the app does not create follow-up emails, schedule sends, track opens, or send anything.

## Phase 2 Department Discovery

Use Discovery to paste one official department homepage or people page at a time. If you paste a homepage, the app first finds the official faculty or people directory and shows that directory URL for approval. Only after you approve the directory does it extract eligible researchers into a review queue.

Each preview must look like a real person and have a supporting signal such as an academic title, profile link, university email, research role, or faculty-card structure. Navigation labels, program names, headings, and news items are rejected. The review card shows the source URL and exact source element before anything can be saved as a candidate.

## Phase 3 Publication Memory

Open a candidate to add publication metadata manually, including a pasted Google Scholar URL or author profile as source context. The app does not scrape Scholar. Publications are deduplicated by DOI, arXiv ID, OpenAlex ID, or title fingerprint. Author identity matches can remain marked for review when affiliation evidence is weak.

## Phase 4 Retrieval and Analysis

For publications with an arXiv ID or valid PDF URL, use Retrieve PDF from the candidate page. Downloads go through the safe fetcher and must pass PDF validation before storage. Open a paper to create a structured local analysis; the local analyzer extracts only evidence present in parsed text and records limitations, future work, contribution areas, and overclaim risks.

Later phases will document:

- Profile setup.
- Asset configuration.
- Candidate tracking.
- Manual paper upload.
- Paper analysis review.
- Draft review.
- Outlook draft creation.
- Follow-up tracking.
