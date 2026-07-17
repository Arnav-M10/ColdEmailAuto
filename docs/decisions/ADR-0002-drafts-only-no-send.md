# ADR-0002: Drafts-Only Email Boundary

## Status

Accepted

## Context

The application exists to support careful, human-supervised outreach. It must never become an automatic sending or mass outreach system.

## Decision

The application will not implement email sending. Future Outlook integration may create reviewable drafts only after explicit user approval.

The project must not include:

- Microsoft Graph `Mail.Send`.
- SMTP.
- A send endpoint.
- A send button.
- Scheduled send.
- Browser automation that clicks Send.
- Any indirect sending workaround.

## Consequences

- Every phase must preserve the no-send boundary.
- Tests must include a no-send regression check once the test suite exists.
- Documentation and code review must treat any sending capability as a safety regression.

