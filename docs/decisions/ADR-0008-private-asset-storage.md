# ADR-0008: Private Asset Storage for Resume and Portfolio

## Status

Accepted

## Context

The research workflow needs two private PDFs: Arnav's resume and research portfolio. These files
must not be committed to Git or served from the public static directory. Railway deploys from the
Git repository, so ignored local files under `assets/` are absent in production.

Missing portfolio text previously made outreach ranking look like a true zero-similarity score and
could push an automatic workflow into manual publication selection.

## Decision

Use configurable private filesystem paths for required PDFs:

- `PRIVATE_ASSET_DIR`
- `RESUME_PDF_PATH`
- `RESEARCH_PORTFOLIO_PDF_PATH`

The Railway default is a persistent volume mounted at `/data`, with private files stored under
`/data/private_assets`. A secure Settings setup page accepts uploads only when `ADMIN_SETUP_TOKEN`
matches using constant-time comparison and the existing CSRF token is valid.

Uploaded files are validated before storage:

- PDF magic bytes
- `application/pdf` MIME type
- configured size limit
- pypdf readability
- non-empty extracted text for the research portfolio

Portfolio text extraction is cached by PDF SHA-256 and extraction version. If portfolio input is
missing or invalid during the automatic workflow, the workflow pauses as
`WAITING_FOR_PORTFOLIO_INPUT` and preserves the same `ResearchWorkflowRun`.

## Consequences

Private PDFs remain outside Git and outside `/static`.

Railway deployments require a persistent volume and setup token before automatic research workflows
can complete.

Automatic workflows no longer fall back to manual paper selection just because portfolio input is
missing.

No mailbox access, email sending, SMTP, Gmail, Outlook, or `Mail.Send` capability is introduced.
