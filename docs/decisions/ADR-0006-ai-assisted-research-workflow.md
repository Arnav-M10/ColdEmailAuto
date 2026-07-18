# ADR-0006: AI-Assisted Research Workflow

## Status

Accepted.

## Context

The publication list was useful for manual review, but the daily workflow still required too many clicks before reaching the useful stopping point: a selected paper, lawful PDF, paper analysis, and draft ready for human review. The product direction is now to rank papers automatically and continue through retrieval and analysis when a paper is clearly suitable.

## Decision

Add a local `ResearchWorkflowRun` orchestration record and a candidate-level `Run Research Workflow` action.

When `AUTO_SELECT_PAPER=true`, the workflow:

1. ensures publications exist for the candidate;
2. ranks papers by outreach score;
3. skips unsuitable papers, including papers without lawful full text;
4. records the selected paper and alternatives considered;
5. approves that selected paper for retrieval with an automatic-selection note;
6. retrieves the lawful PDF through the safe fetcher;
7. extracts text through the existing PDF pipeline;
8. runs provider-backed paper analysis through the generic AI provider interface;
9. requires explicit evidence before drafting;
10. generates a local draft and stops for human review.

The workflow never sends email and does not add Outlook integration.

Manual override remains available through `Choose a different paper`. Manual PDF retrieval routes still enforce the explicit paper approval gate from ADR-0004. This ADR supersedes ADR-0004 only for the automatic workflow's own selected paper.

## Consequences

- Users can move from candidate to reviewable paper/draft with one primary action.
- Workflow failures are preserved with the failed stage and reason, so retry is possible without hiding errors.
- Missing or invalid required resume/portfolio assets block draft readiness.
- The paper detail page becomes the review surface for selected-paper provenance, retrieval source, PDF hash, extraction status, selection reasons, and alternatives considered.
- Tests must cover auto-selection, skip rules, persistence, manual override, route continuation, and the no-send boundary.
