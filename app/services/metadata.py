import json
import re
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.candidate import Candidate
from app.models.publication import Authorship, Publication

TITLE_WORD_RE = re.compile(r"[a-z0-9]+")
ARXIV_RE = re.compile(r"arxiv[:/ ]+([0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?)", re.I)
DOI_PREFIX_RE = re.compile(r"^https?://(?:dx\.)?doi\.org/", re.I)
RECENT_YEAR_THRESHOLD = 2021
LARGE_AUTHOR_WARNING_THRESHOLD = 25


class MetadataClientLike(Protocol):
    def get_json(self, url: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class PublicationMetadata:
    title: str
    year: int | None
    venue: str | None
    doi: str | None
    arxiv_id: str | None
    openalex_id: str | None
    source: str
    open_access_url: str | None
    pdf_url: str | None
    authors: list[str]
    author_institutions: list[str]
    raw: dict[str, Any]


@dataclass(frozen=True)
class AuthorIdentityMatch:
    confidence: float
    author_position: int | None
    author_count: int
    status: str
    warnings: list[str]


@dataclass(frozen=True)
class PublicationScore:
    score: float
    connection_summary: str
    warnings: list[str]


class HTTPJSONClient:
    def get_json(self, url: str) -> dict[str, Any]:
        import httpx

        response = httpx.get(url, timeout=12.0)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Metadata API returned non-object JSON.")
        return data


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = DOI_PREFIX_RE.sub("", value.strip()).lower()
    return cleaned or None


def extract_arxiv_id(value: str | None) -> str | None:
    if not value:
        return None
    match = ARXIV_RE.search(value)
    return match.group(1).lower() if match else None


def title_fingerprint(title: str) -> str:
    return " ".join(TITLE_WORD_RE.findall(title.lower()))[:500]


def deduplicate_metadata(items: list[PublicationMetadata]) -> list[PublicationMetadata]:
    seen: set[str] = set()
    deduped: list[PublicationMetadata] = []
    for item in items:
        key = item.doi or item.arxiv_id or item.openalex_id or title_fingerprint(item.title)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


class OpenAlexClient:
    base_url = "https://api.openalex.org"

    def __init__(self, client: MetadataClientLike | None = None) -> None:
        self.client = client or HTTPJSONClient()

    def search_authors(self, query: str) -> list[dict[str, Any]]:
        url = f"{self.base_url}/authors?{urlencode({'search': query, 'per-page': '10'})}"
        data = self.client.get_json(url)
        results = data.get("results", [])
        return results if isinstance(results, list) else []

    def works_for_author(self, openalex_author_id: str) -> list[PublicationMetadata]:
        query = {
            "filter": f"authorships.author.id:{openalex_author_id}",
            "per-page": "25",
        }
        url = f"{self.base_url}/works?{urlencode(query)}"
        data = self.client.get_json(url)
        results = data.get("results", [])
        if not isinstance(results, list):
            return []
        return [parse_openalex_work(item) for item in results if isinstance(item, dict)]


class CrossrefClient:
    base_url = "https://api.crossref.org"

    def __init__(self, client: MetadataClientLike | None = None) -> None:
        self.client = client or HTTPJSONClient()

    def works_by_query(self, query: str) -> list[PublicationMetadata]:
        url = f"{self.base_url}/works?{urlencode({'query.bibliographic': query, 'rows': '20'})}"
        data = self.client.get_json(url)
        message = data.get("message", {})
        items = message.get("items", []) if isinstance(message, dict) else []
        if not isinstance(items, list):
            return []
        return [parse_crossref_work(item) for item in items if isinstance(item, dict)]


def parse_openalex_work(item: dict[str, Any]) -> PublicationMetadata:
    authorships = item.get("authorships", [])
    authors: list[str] = []
    institutions: list[str] = []
    if isinstance(authorships, list):
        for authorship in authorships:
            if not isinstance(authorship, dict):
                continue
            author = authorship.get("author", {})
            if isinstance(author, dict) and isinstance(author.get("display_name"), str):
                authors.append(author["display_name"])
            for institution in authorship.get("institutions", []) or []:
                if isinstance(institution, dict):
                    display_name = institution.get("display_name")
                    if isinstance(display_name, str):
                        institutions.append(display_name)
    primary_location = item.get("primary_location", {})
    landing_url = None
    pdf_url = None
    if isinstance(primary_location, dict):
        landing_url = primary_location.get("landing_page_url")
        pdf_url = primary_location.get("pdf_url")
    return PublicationMetadata(
        title=str(item.get("title") or "Untitled"),
        year=item.get("publication_year")
        if isinstance(item.get("publication_year"), int)
        else None,
        venue=_openalex_venue(item),
        doi=normalize_doi(item.get("doi") if isinstance(item.get("doi"), str) else None),
        arxiv_id=extract_arxiv_id(item.get("doi") if isinstance(item.get("doi"), str) else None),
        openalex_id=item.get("id") if isinstance(item.get("id"), str) else None,
        source="openalex",
        open_access_url=landing_url if isinstance(landing_url, str) else None,
        pdf_url=pdf_url if isinstance(pdf_url, str) else None,
        authors=authors,
        author_institutions=sorted(set(institutions)),
        raw=item,
    )


def _openalex_venue(item: dict[str, Any]) -> str | None:
    host_venue = item.get("host_venue", {})
    if isinstance(host_venue, dict):
        display_name = host_venue.get("display_name")
        if isinstance(display_name, str):
            return display_name
    primary_location = item.get("primary_location", {})
    if isinstance(primary_location, dict):
        source = primary_location.get("source", {})
        if isinstance(source, dict):
            display_name = source.get("display_name")
            if isinstance(display_name, str):
                return display_name
    return None


def parse_crossref_work(item: dict[str, Any]) -> PublicationMetadata:
    raw_title = item.get("title", [])
    title = raw_title[0] if isinstance(raw_title, list) and raw_title else "Untitled"
    authors: list[str] = []
    for author in item.get("author", []) or []:
        if not isinstance(author, dict):
            continue
        given = author.get("given") if isinstance(author.get("given"), str) else ""
        family = author.get("family") if isinstance(author.get("family"), str) else ""
        name = f"{given} {family}".strip()
        if name:
            authors.append(name)
    year = _crossref_year(item)
    link_items = item.get("link", [])
    pdf_url = None
    if isinstance(link_items, list):
        for link in link_items:
            if isinstance(link, dict) and "pdf" in str(link.get("content-type", "")).lower():
                candidate_url = link.get("URL")
                if isinstance(candidate_url, str):
                    pdf_url = candidate_url
                    break
    return PublicationMetadata(
        title=str(title),
        year=year,
        venue=_crossref_venue(item),
        doi=normalize_doi(item.get("DOI") if isinstance(item.get("DOI"), str) else None),
        arxiv_id=extract_arxiv_id(item.get("DOI") if isinstance(item.get("DOI"), str) else None),
        openalex_id=None,
        source="crossref",
        open_access_url=item.get("URL") if isinstance(item.get("URL"), str) else None,
        pdf_url=pdf_url,
        authors=authors,
        author_institutions=[],
        raw=item,
    )


def _crossref_year(item: dict[str, Any]) -> int | None:
    for key in ("published-print", "published-online", "created"):
        value = item.get(key, {})
        if isinstance(value, dict):
            date_parts = value.get("date-parts", [])
            if (
                isinstance(date_parts, list)
                and date_parts
                and isinstance(date_parts[0], list)
                and date_parts[0]
                and isinstance(date_parts[0][0], int)
            ):
                return date_parts[0][0]
    return None


def _crossref_venue(item: dict[str, Any]) -> str | None:
    raw = item.get("container-title", [])
    if isinstance(raw, list) and raw and isinstance(raw[0], str):
        return raw[0]
    return None


def match_candidate_author(
    candidate: Candidate,
    metadata: PublicationMetadata,
) -> AuthorIdentityMatch:
    normalized_candidate = candidate.full_name.strip().lower()
    author_count = len(metadata.authors)
    warnings: list[str] = []
    position = None
    for index, author in enumerate(metadata.authors, start=1):
        if author.strip().lower() == normalized_candidate:
            position = index
            break
    confidence = 0.0
    status = "REVIEW_REQUIRED"
    if position is not None:
        confidence = 0.7
        status = "MATCHED"
        if candidate.institution and any(
            candidate.institution.lower() in institution.lower()
            for institution in metadata.author_institutions
        ):
            confidence = 0.9
        elif metadata.author_institutions:
            warnings.append("Name matched, but affiliation did not clearly match.")
            confidence = 0.75
    else:
        warnings.append("Candidate name was not found in the author list.")
    if author_count > LARGE_AUTHOR_WARNING_THRESHOLD:
        warnings.append("Large author list; candidate contribution may be unclear.")
    return AuthorIdentityMatch(
        confidence=confidence,
        author_position=position,
        author_count=author_count,
        status=status if confidence >= 0.8 else "REVIEW_REQUIRED",
        warnings=warnings,
    )


def score_publication_for_candidate(
    candidate: Candidate,
    metadata: PublicationMetadata,
    match: AuthorIdentityMatch,
) -> PublicationScore:
    text = f"{metadata.title} {candidate.research_area or ''}".lower()
    overlap_terms = [term for term in candidate_terms(candidate) if term in text]
    score = 0.0
    warnings = list(match.warnings)
    if metadata.year and metadata.year >= RECENT_YEAR_THRESHOLD:
        score += 20
    else:
        warnings.append("Publication is outside the default recent-paper window.")
    if match.author_position == 1:
        score += 25
    elif match.author_position == match.author_count and match.author_count > 1:
        score += 18
    elif match.author_position:
        score += 10
    score += min(30, len(overlap_terms) * 10)
    if metadata.pdf_url or metadata.open_access_url:
        score += 15
    if match.confidence >= 0.8:
        score += 10
    if not overlap_terms:
        warnings.append("No strong text overlap with the candidate research area.")
    connection = ", ".join(overlap_terms) if overlap_terms else "Needs manual review"
    return PublicationScore(score=score, connection_summary=connection, warnings=warnings)


def candidate_terms(candidate: Candidate) -> set[str]:
    text = f"{candidate.research_area or ''} {candidate.notes or ''}".lower()
    return {word for word in TITLE_WORD_RE.findall(text) if len(word) > 4}


def upsert_publication_with_authorship(
    session: Session,
    *,
    candidate: Candidate,
    metadata: PublicationMetadata,
) -> tuple[Publication, Authorship]:
    fingerprint = title_fingerprint(metadata.title)
    publication = session.scalars(
        select(Publication).where(
            or_(
                Publication.doi == metadata.doi,
                Publication.arxiv_id == metadata.arxiv_id,
                Publication.openalex_id == metadata.openalex_id,
                Publication.title_fingerprint == fingerprint,
            ),
        ),
    ).first()
    if publication is None:
        publication = Publication(
            title=metadata.title,
            title_fingerprint=fingerprint,
            year=metadata.year,
            venue=metadata.venue,
            doi=metadata.doi,
            arxiv_id=metadata.arxiv_id,
            openalex_id=metadata.openalex_id,
            source=metadata.source,
            open_access_url=metadata.open_access_url,
            pdf_url=metadata.pdf_url,
            author_count=len(metadata.authors) or None,
            metadata_json=json.dumps(metadata.raw),
        )
        session.add(publication)
        session.flush()
    match = match_candidate_author(candidate, metadata)
    scored = score_publication_for_candidate(candidate, metadata, match)
    authorship = session.scalars(
        select(Authorship).where(
            Authorship.candidate_id == candidate.id,
            Authorship.publication_id == publication.id,
        ),
    ).first()
    if authorship is None:
        authorship = Authorship(candidate_id=candidate.id, publication_id=publication.id)
        session.add(authorship)
    authorship.author_position = match.author_position
    authorship.author_count = match.author_count or None
    authorship.role = authorship_role(match.author_position, match.author_count)
    authorship.identity_confidence = match.confidence
    authorship.match_status = match.status
    authorship.score = scored.score
    authorship.connection_summary = scored.connection_summary
    authorship.warnings_json = json.dumps(scored.warnings)
    return publication, authorship


def authorship_role(position: int | None, author_count: int) -> str | None:
    if position is None:
        return None
    if position == 1:
        return "first_author"
    if position == author_count and author_count > 1:
        return "last_author"
    if author_count > LARGE_AUTHOR_WARNING_THRESHOLD:
        return "large_consortium"
    return "coauthor"
