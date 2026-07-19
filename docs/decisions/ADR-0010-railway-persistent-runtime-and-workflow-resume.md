# ADR-0010: Railway Persistent Runtime Storage and Workflow Resume Context

## Status

Accepted

## Context

Railway redeploys replace the application filesystem, while the configured persistent volume is
mounted at `/data`. SQLAlchemy interprets `sqlite:///data/outreach.db` as a relative path named
`data/outreach.db`, not as `/data/outreach.db`. Runtime caches and downloaded PDFs also need to live
on the persistent volume in production.

The automatic research workflow can pause for OpenAlex author confirmation. A boolean
`resume_workflow` flag was not enough context to guarantee the confirmation POST resumed the same
server-side `ResearchWorkflowRun`.

## Decision

Use `DATABASE_URL=sqlite:////data/outreach.db` on Railway and expose `RUNTIME_DATA_DIR=/data` for
runtime database-adjacent storage. Cache directories, portfolio text extraction, AI usage tracking,
and stored paper files use the resolved runtime data directory outside the ephemeral repository when
configured.

When a research workflow pauses for OpenAlex author confirmation, include the waiting workflow ID in
the confirmation URL and hidden form. After confirmation, the application reloads that exact waiting
workflow for the candidate and resumes automatic publication retrieval, ranking, PDF retrieval,
analysis, drafting, and manual draft review.

Manual publication decision forms are shown only on the explicit publication-selection page. The
candidate detail page can display publication context, but it does not present manual paper approval
actions while a workflow is waiting for author confirmation or portfolio input.

## Consequences

Railway deployments must configure an absolute SQLite URL with four slashes and mount the volume at
`/data`.

Startup continues to create missing tables and additive compatibility columns, but it does not delete
or recreate the database.

The author-confirmation flow preserves one workflow run instead of creating a replacement run after
confirmation.

No Outlook, Gmail, SMTP, mailbox access, browser send automation, or email-sending capability is
introduced.
