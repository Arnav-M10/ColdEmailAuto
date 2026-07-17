# ADR-0003: Safe Web Retrieval Boundary

## Status

Accepted.

## Context

Phase 2 begins controlled department-page imports and later phases retrieve public metadata and open-access PDFs. These features introduce SSRF, path traversal, rate-limit, robots, copyright, malformed-content, and prompt-injection risks.

## Decision

All remote retrieval must pass through a safe fetcher boundary before parsing or persistence. The boundary validates URL scheme and host category, blocks local/private network targets, resolves hostnames before requests, revalidates redirects, checks robots policy for page imports, applies per-domain delay hooks, caps response size, and validates expected content.

Open-access PDF retrieval may use a small maintained allowlist of public full-text hosts in addition to official university domains and public APIs; arbitrary model- or metadata-provided PDF hosts remain blocked unless explicitly added to the allowlist.

Discovery candidates from imported pages are stored as review previews, not permanent candidates. The user must explicitly save reviewed candidates.

## Consequences

- Discovery and paper retrieval share one defensive network path.
- Tests can mock the fetcher without real network access.
- Some legitimate pages may require manual handling if they fail HTTPS, robots, size, or content checks.
- Future integrations must extend the allowlist deliberately rather than fetching arbitrary model-generated URLs.
