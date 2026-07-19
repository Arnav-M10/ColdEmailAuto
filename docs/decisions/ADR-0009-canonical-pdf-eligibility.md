# ADR-0009: Canonical PDF Eligibility for Automatic Workflows

## Status

Accepted

## Context

Publication ranking, UI labels, automatic paper selection, and PDF retrieval used overlapping but
different checks for full-text availability. That allowed a workflow to display a paper as selected
with a PDF URL while also entering `WAITING_FOR_MANUAL_PAPER_SELECTION`.

## Decision

Use `PDFEligibility` from `app.services.retrieval` as the canonical full-text decision for
publication UI, researcher-intelligence scoring, workflow suitability, and retrieval planning.

The eligibility result distinguishes:

- `DIRECT_PDF_URL`
- `OPEN_ACCESS_LANDING_PAGE_ONLY`
- `DOI_ONLY`
- `ARXIV_ID_AVAILABLE`
- `REPOSITORY_RECORD_WITHOUT_PDF`
- `NO_LAWFUL_SOURCE`
- `INVALID_OR_UNSAFE_URL`

Automatic workflows now rank suitable papers, attempt PDF retrieval, and fall back to the next
ranked suitable paper when retrieval fails. `WAITING_FOR_MANUAL_PAPER_SELECTION` is used only after
no paper passes suitability or after all suitable papers have failed retrieval.

## Consequences

The workflow no longer treats a metadata-only fallback as an active selected paper.

Retrieval attempts and rejection reasons are stored in `retrieval_result_json` and
`rejected_alternatives_json`.

Logs record workflow transitions and PDF eligibility metadata without secrets, private file
contents, PDF contents, or email bodies.

No Outlook, Gmail, SMTP, mailbox access, or email-sending capability is added.
