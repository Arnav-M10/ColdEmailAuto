import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.candidate import Candidate, CandidateStatus
from app.models.paper import PaperFile
from app.models.publication import Publication
from app.services.papers import store_manual_pdf
from app.services.web_safety import FetchResult, SafeFetcher, SafeFetchError, validate_url


class PDFFetcherLike(Protocol):
    def fetch(self, url: str, *, expected: str = "pdf") -> FetchResult: ...


@dataclass(frozen=True)
class RetrievalPlan:
    url: str
    license_note: str
    rank: int
    source_type: str


@dataclass(frozen=True)
class RetrievalFailure:
    url: str
    source_type: str
    reason: str


def arxiv_pdf_url(arxiv_id: str) -> str:
    cleaned = arxiv_id.strip().removesuffix(".pdf")
    return f"https://arxiv.org/pdf/{cleaned}"


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().strip(".")


def _is_arxiv_url(url: str) -> bool:
    return _host(url) in {"arxiv.org", "export.arxiv.org"}


def _looks_like_pdf_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    return path.endswith(".pdf") or "/pdf" in path or _is_arxiv_url(url)


def _arxiv_url_to_pdf(url: str) -> str:
    parsed = urlparse(url.strip())
    if _host(url) not in {"arxiv.org", "export.arxiv.org"}:
        return url
    path = parsed.path.strip("/")
    if path.startswith("abs/"):
        return arxiv_pdf_url(path.removeprefix("abs/"))
    if path.startswith("pdf/"):
        return f"https://arxiv.org/{path}"
    return url


def _source_rank(url: str, *, source_type: str) -> int:
    validation = validate_url(url, resolve_dns=False)
    if _is_arxiv_url(url):
        return 1
    if source_type.startswith("openalex"):
        return 5
    if validation.category == "official_university_domain":
        return 2
    if validation.category == "approved_public_full_text_host":
        return 4
    return 6


def _license_note(url: str, *, source_type: str) -> str:
    if _is_arxiv_url(url):
        return "arXiv public PDF."
    category = validate_url(url, resolve_dns=False).category
    if category == "official_university_domain":
        return "Official university or institutional public PDF."
    if category == "approved_public_full_text_host":
        return "Approved public full-text host PDF."
    if source_type.startswith("openalex"):
        return "OpenAlex open-access location PDF."
    return "Lawful public PDF URL from publication metadata."


def _json_object(value: str) -> dict[str, object]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _string_items_from_openalex_locations(raw: dict[str, object]) -> Iterator[tuple[str, str]]:
    for key in ("primary_location", "best_oa_location"):
        location = raw.get(key)
        if isinstance(location, dict):
            pdf_url = location.get("pdf_url")
            if isinstance(pdf_url, str):
                yield pdf_url, f"openalex_{key}"
    locations = raw.get("locations")
    if isinstance(locations, list):
        for location in locations:
            if not isinstance(location, dict):
                continue
            if location.get("is_oa") is False:
                continue
            pdf_url = location.get("pdf_url")
            if isinstance(pdf_url, str):
                yield pdf_url, "openalex_oa_location"


def _candidate_plan(url: str, *, source_type: str) -> RetrievalPlan | None:
    cleaned = _arxiv_url_to_pdf(url.strip())
    if not cleaned or not _looks_like_pdf_url(cleaned):
        return None
    try:
        rank = _source_rank(cleaned, source_type=source_type)
        note = _license_note(cleaned, source_type=source_type)
    except SafeFetchError:
        return None
    return RetrievalPlan(url=cleaned, license_note=note, rank=rank, source_type=source_type)


def plan_publication_pdf_retrieval_candidates(publication: Publication) -> list[RetrievalPlan]:
    plans: list[RetrievalPlan] = []
    if publication.arxiv_id:
        plans.append(
            RetrievalPlan(
                url=arxiv_pdf_url(publication.arxiv_id),
                license_note="arXiv public PDF.",
                rank=1,
                source_type="arxiv_id",
            ),
        )
    for url, source_type in (
        (publication.pdf_url, f"{publication.source}_pdf_url"),
        (publication.open_access_url, f"{publication.source}_open_access_url"),
    ):
        if url:
            plan = _candidate_plan(url, source_type=source_type)
            if plan is not None:
                plans.append(plan)
    raw = _json_object(publication.metadata_json)
    for url, source_type in _string_items_from_openalex_locations(raw):
        plan = _candidate_plan(url, source_type=source_type)
        if plan is not None:
            plans.append(plan)

    unique: dict[str, RetrievalPlan] = {}
    for plan in sorted(plans, key=lambda item: (item.rank, item.source_type, item.url)):
        unique.setdefault(plan.url, plan)
    return list(unique.values())


def plan_publication_pdf_retrieval(publication: Publication) -> RetrievalPlan | None:
    plans = plan_publication_pdf_retrieval_candidates(publication)
    return plans[0] if plans else None


def retrieve_publication_pdf(
    session: Session,
    *,
    candidate: Candidate,
    publication: Publication,
    fetcher: PDFFetcherLike | None = None,
) -> PaperFile:
    plans = plan_publication_pdf_retrieval_candidates(publication)
    if not plans:
        candidate.status = CandidateStatus.NO_FULL_TEXT
        raise ValueError(
            "No lawful open-access PDF URL is available for this publication. "
            f"DOI: {publication.doi or 'not recorded'}; source: {publication.source}."
        )
    settings = get_settings()
    fetcher = fetcher or SafeFetcher(max_bytes=settings.max_pdf_size_mb * 1024 * 1024)
    failures: list[RetrievalFailure] = []
    for plan in plans:
        try:
            result = fetcher.fetch(plan.url, expected="pdf")
            filename_seed = publication.arxiv_id or publication.doi or publication.title_fingerprint
            paper_file = store_manual_pdf(
                session,
                candidate=candidate,
                publication_id=publication.id,
                original_filename=f"{filename_seed}.pdf",
                content=result.body,
                source_url=result.final_url,
                license_note=plan.license_note,
            )
        except (SafeFetchError, ValueError) as exc:
            failures.append(
                RetrievalFailure(url=plan.url, source_type=plan.source_type, reason=str(exc)),
            )
            continue
        candidate.status = CandidateStatus.PAPERS_FOUND
        return paper_file
    candidate.status = CandidateStatus.NO_FULL_TEXT
    failure_summary = "; ".join(
        f"{failure.source_type} {failure.url}: {failure.reason}" for failure in failures
    )
    raise ValueError(
        "No lawful PDF could be retrieved. "
        f"DOI: {publication.doi or 'not recorded'}; source: {publication.source}. "
        f"Tried {failure_summary}."
    )
