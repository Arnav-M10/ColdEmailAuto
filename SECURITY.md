# Security Policy

This project is a local, single-user application for careful professor outreach. It handles professional contact data, local documents, draft metadata, and later delegated Outlook access.

## Core Security Rules

- Never add automatic email sending.
- Never request Microsoft Graph `Mail.Send`.
- Never store Outlook tokens in SQLite, source code, `.env`, logs, browser local storage, or exports.
- Never commit real databases, logs, personal PDFs, downloaded papers, resumes, portfolios, token caches, `.env`, or exports.
- Treat webpages, PDFs, model outputs, CSV files, and email content as untrusted input.
- Validate paths and filenames before file storage.
- Bind local development servers to `127.0.0.1` by default.
- Redact secrets and authorization headers from logs.

## Reporting Issues

For local development, record suspected security issues in `docs/THREAT_MODEL.md` or a dedicated issue tracker before implementing a fix. Do not weaken the safety requirements in `PROJECT_SPEC.md`.

