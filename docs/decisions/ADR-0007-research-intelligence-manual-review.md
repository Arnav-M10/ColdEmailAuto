# ADR-0007: Research Intelligence and Manual Outlook Review

## Status

Accepted.

## Context

The workflow should not jump from publication retrieval to a single-paper email without understanding the researcher's broader recent work. It also should not connect to Outlook or Gmail yet. The safe endpoint for this phase is a copy-ready manual review page.

## Decision

Add a deterministic, cacheable researcher-intelligence layer before automatic paper selection. It uses recent publication metadata, abstracts, topics, official profile context when available, and the local portfolio map to build themes, clusters, methods, datasets, collaborators, active-project inferences, and portfolio connections.

The automatic selector combines existing outreach score with an email-usefulness score. It still rejects papers without lawful full text, unsuitable publication types, unclear author identity, stale works, weak portfolio fit, oversized author lists, and unsuitable authorship roles.

Add a manual Outlook review page that shows recipient, source, subject, body, word count, selected paper, summary, evidence map, attachments, readiness warnings, sentence-level claim checks, and clipboard-copy buttons. Clipboard use is browser-local only. The app does not open Outlook, access mailboxes, request Microsoft/Google mail permissions, or send email.

## Consequences

- Broader-research context is visible and reusable from the candidate page.
- Draft readiness is blocked by missing official email, invalid attachments, forbidden wording, wrong length, paragraph-count errors, or unsupported factual sentences.
- Gemini usage remains focused on the selected full paper, and cached analysis avoids duplicate calls.
- Cost controls track provider calls with daily and per-workflow limits.
- Speculative profile details may be shown for human review but are not used as factual email claims.
