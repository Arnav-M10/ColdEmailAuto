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
