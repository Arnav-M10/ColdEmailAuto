# Data Model

The normalized data model will be introduced during Phase 0 database work and expanded in Phase 1.

Required future entities include:

- Candidate.
- Institution.
- EmailAddress.
- Publication.
- Authorship.
- PaperFile.
- PaperAnalysis.
- EvidenceItem.
- Draft.
- OutreachEvent.
- FollowUpTask.
- AuditEvent.
- Job.

Status transitions must enforce the safety requirements in `PROJECT_SPEC.md`.

## Phase 0 Foundation Tables

Phase 0 creates a deliberately small foundation schema:

- `candidates`: minimal candidate identity and status.
- `audit_events`: append-only audit event records for future important actions.
- `jobs`: local job tracking with idempotency keys.

The full normalized model will be expanded in Phase 1 and later phases. Runtime SQLite databases are local files and must not be committed.

## Phase 1 Manual Tracker Tables

Phase 1 adds tables for local manual tracking:

- `email_addresses` with official-source provenance.
- `paper_files` for safely stored manual PDF uploads.
- `paper_analyses` and `evidence_items` for traceable paper claims.
- `drafts` for reviewable local email drafts.
- `outreach_events` for auditable candidate history.
- `follow_up_tasks` for manual follow-up planning.

Status transitions are validated in application services and must not bypass the full-paper analysis requirement before draft readiness.
