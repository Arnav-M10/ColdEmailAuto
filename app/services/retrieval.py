from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.orm import Session

from app.models.candidate import Candidate, CandidateStatus
from app.models.paper import PaperFile
from app.models.publication import Publication
from app.services.papers import store_manual_pdf
from app.services.web_safety import FetchResult, SafeFetcher


class PDFFetcherLike(Protocol):
    def fetch(self, url: str, *, expected: str = "pdf") -> FetchResult: ...


@dataclass(frozen=True)
class RetrievalPlan:
    url: str
    license_note: str


def arxiv_pdf_url(arxiv_id: str) -> str:
    cleaned = arxiv_id.strip().removesuffix(".pdf")
    return f"https://arxiv.org/pdf/{cleaned}"


def plan_publication_pdf_retrieval(publication: Publication) -> RetrievalPlan | None:
    if publication.pdf_url:
        return RetrievalPlan(url=publication.pdf_url, license_note="PDF URL from metadata.")
    if publication.arxiv_id:
        return RetrievalPlan(
            url=arxiv_pdf_url(publication.arxiv_id),
            license_note="arXiv public PDF.",
        )
    return None


def retrieve_publication_pdf(
    session: Session,
    *,
    candidate: Candidate,
    publication: Publication,
    fetcher: PDFFetcherLike | None = None,
) -> PaperFile:
    plan = plan_publication_pdf_retrieval(publication)
    if plan is None:
        candidate.status = CandidateStatus.NO_FULL_TEXT
        raise ValueError("No lawful open-access PDF URL is available for this publication.")
    fetcher = fetcher or SafeFetcher()
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
    candidate.status = CandidateStatus.PAPERS_FOUND
    return paper_file
