# Codex Operating Guide

This repository implements the Professor Outreach Manager described in `PROJECT_SPEC.md`.

Future Codex sessions must:

- Read `PROJECT_SPEC.md` before changing code, data models, or safety policy.
- Preserve the drafts-only architecture.
- Never add automatic email sending.
- Never request or depend on Microsoft Graph `Mail.Send`.
- Never add SMTP, browser automation that clicks Send, scheduled send, or any indirect sending path.
- Maintain evidence traceability from paper text to technical email sentence.
- Never generate paper-specific drafts without a complete, lawfully obtained paper analysis.
- Never guess email addresses.
- Never bypass paywalls, robots restrictions, CAPTCHA, or access controls.
- Protect secrets, access tokens, personal PDFs, logs, local databases, and exports from commits.
- Keep changes small, reviewed, documented, and tested.
- Run the relevant quality gates before claiming completion.
- Update docs and changelog when behavior, setup, safety policy, or architecture changes.
- Ask before altering product safety policy or weakening any requirement in `PROJECT_SPEC.md`.

Phase discipline:

- Phase 0 is repository foundation only.
- Do not begin Outlook, OpenAlex, Crossref, arXiv retrieval, crawling, or automated discovery until earlier phases are complete and reviewed.
- Include a no-send regression test in every phase once the test suite exists.

