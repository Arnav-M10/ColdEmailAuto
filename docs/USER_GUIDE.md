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

Discovery previews are screened before saving. Emeritus, retired, inactive, and duplicate/local-contacted people are excluded by default; hardware-heavy profiles without a clear computational path and same-group overlaps are flagged. Each score shows simple evidence-based reasons, and exclusions can be manually overridden from the review card.

The dashboard shows local workflow counts for imports, discovered and excluded previews, shortlisted candidates, papers, PDFs, analyses, drafts awaiting review, missing email, missing full text, and failures.

## Phase 3 Publication Memory

Open Publications to see saved candidates and use `Fetch Publications` for one candidate at a time. You can also open a candidate and use the same action from the candidate detail page. The app retrieves recent publications from OpenAlex and confirms DOI metadata through Crossref. If OpenAlex returns multiple plausible authors, the app shows an HTML confirmation page with ranked author profiles, affiliation evidence, topics, ORCID, OpenAlex ID, and profile links. After you confirm an author, the app stores the selected OpenAlex author ID locally, retrieves publications immediately, and continues according to the configured workflow. If publications for that stored author already exist, the app skips another lookup and shows them immediately. Results are cached under ignored local cache files and are deduplicated by DOI, arXiv ID, OpenAlex ID, or title fingerprint.

The publication-selection page defaults to `Best outreach match`, which combines portfolio similarity, confirmed author role, author count, recency, lawful PDF availability, review-article status, and citation count. You can also sort by newest, highest citation count, or fewest authors. Each paper shows score reasons and component values so the ranking can be audited before you approve a paper.

You can still add publication metadata manually, including a pasted Google Scholar URL or author profile as source context. The app does not scrape Scholar. Author identity matches can remain marked for review when affiliation evidence is weak.

Publication rows are ranked for manual review before any manual PDF retrieval. Each row shows the title, year, author count, candidate author position, candidate role, fit score, match explanation, full-text availability, and ranking warnings. You must approve a paper before the manual retrieval route will retrieve a PDF or run analysis on a publication-linked PDF.

## Phase 4 Retrieval and Analysis

For approved publications with an arXiv ID or valid PDF URL, use Retrieve PDF from the candidate page. Retrieval tries arXiv first, then official university or institutional public PDFs, then approved public full-text hosts, then OpenAlex open-access PDF locations. Downloads go through the safe fetcher and must pass PDF validation before storage. If no lawful PDF can be retrieved, the candidate is marked `NO_FULL_TEXT` and the DOI/source remain visible for manual handling.

Use `Run Research Workflow` from a candidate page for the default assisted path. The workflow finds or reuses publications, ranks papers, skips unsuitable papers and papers without lawful full text, selects the best available paper, retrieves the PDF, extracts text, runs Gemini-backed analysis through the provider interface, generates a local draft, and stops for review. The candidate page shows the current workflow stage, selected paper, PDF status, failures, and retry action. The selected paper page shows DOI, OpenAlex ID, authorship position, selection score, score reasons, lawful PDF source, SHA-256 hash, extraction status, retrieval result, and alternatives considered.

Use `Choose a different paper` when you want to override the automatic selection.

Open a paper to create a structured local analysis; the local analyzer extracts only evidence present in parsed text and records limitations, future work, contribution areas, and overclaim risks.

Provider-backed AI analysis uses the configured `AI_PROVIDER`; Gemini is the default. If the Gemini key is missing or invalid, the app shows a setup error and does not create an analysis. Provider output must pass structured validation and evidence-grounding checks before it is saved.

Later phases will document:

- Profile setup.
- Asset configuration.
- Candidate tracking.
- Manual paper upload.
- Paper analysis review.
- Draft review.
- Outlook draft creation.
- Follow-up tracking.
