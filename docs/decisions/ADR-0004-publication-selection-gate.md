# ADR-0004: Publication Selection Gate

## Status

Accepted.

## Context

Live publication metadata can include ambiguous author identities, large collaborations, weak keyword matches, stale papers, and papers that are technically open access but not useful for a highly personalized outreach draft. Retrieval and analysis are higher-trust workflow steps because they can make a weak match feel more authoritative than it is.

## Decision

Publication metadata may be imported and ranked automatically, but PDF retrieval and publication-linked analysis require explicit user approval of the specific paper first.

The review UI must show the paper title, year, author count, candidate author position, candidate role, fit score, match explanation, full-text availability, and ranking warnings before approval. The backend enforces the same gate on retrieval and analysis routes so direct URLs cannot bypass the decision.

## Consequences

- Users make one deliberate selection before the app downloads or analyzes a publication.
- Ambiguous or weakly matched papers stay useful as context without becoming evidence for drafts too early.
- The UI has one extra approval step, but the added friction protects personalization quality and evidence discipline.
- Future AI analysis and Outlook draft creation must keep depending on approved, evidence-backed local state rather than raw publication search results.
