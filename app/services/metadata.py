import json
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from functools import lru_cache
from hashlib import sha256
from math import log10, sqrt
from pathlib import Path
from time import monotonic, sleep
from typing import Any, Protocol
from urllib.parse import quote, urlencode, urlparse

from pypdf import PdfReader
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.candidate import Candidate
from app.models.publication import Authorship, Publication
from app.services.assets import PORTFOLIO_PATH
from app.services.web_safety import SafeFetchError, validate_url

TITLE_WORD_RE = re.compile(r"[a-z0-9]+")
ARXIV_RE = re.compile(r"arxiv[:/ ]+([0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?)", re.I)
DOI_PREFIX_RE = re.compile(r"^https?://(?:dx\.)?doi\.org/", re.I)
OPENALEX_AUTHOR_RE = re.compile(r"^(?:https://openalex\.org/)?(A[0-9]+)$", re.I)
RECENT_YEAR_THRESHOLD = 2021
LARGE_AUTHOR_WARNING_THRESHOLD = 25
PORTFOLIO_TEXT_EXTRACTION_VERSION = "pypdf-v1"


class PortfolioInputUnavailable(ValueError):
    pass


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
    citation_count: int = 0
    work_type: str | None = None
    abstract_text: str | None = None
    topics: list[str] = field(default_factory=list)
    author_openalex_ids: list[str | None] = field(default_factory=list)
    corresponding_author_positions: set[int] = field(default_factory=set)


@dataclass(frozen=True)
class AuthorIdentityMatch:
    confidence: float
    author_position: int | None
    author_count: int
    confirmed_author_present: bool
    is_corresponding: bool
    status: str
    warnings: list[str]


@dataclass(frozen=True)
class OpenAlexAuthorCandidate:
    openalex_id: str
    display_name: str
    orcid: str | None
    institutions: list[str]
    works_count: int
    recent_works_count: int
    confidence: float
    reasons: list[str]
    raw: dict[str, Any]
    current_institutions: list[str] = field(default_factory=list)
    previous_institutions: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    profile_url: str | None = None


@dataclass(frozen=True)
class PublicationScore:
    score: float
    connection_summary: str
    warnings: list[str]
    components: dict[str, float]
    reasons: list[str]


@dataclass(frozen=True)
class PortfolioTextStatus:
    available: bool
    text: str
    status: str
    reason: str | None
    source_path: str
    sha256: str | None = None
    cache_path: str | None = None


@dataclass(frozen=True)
class PublicationRetrievalResult:
    author: OpenAlexAuthorCandidate
    imported_count: int
    review_required_count: int
    skipped_count: int
    messages: list[str]


@dataclass(frozen=True)
class CandidatePublicationReview:
    authorship: Authorship
    publication: Publication
    warnings: list[str]
    score_components: dict[str, float]
    score_reasons: list[str]
    full_text_label: str
    full_text_available: bool


class HTTPJSONClient:
    def __init__(
        self,
        *,
        cache_dir: Path | None = None,
        min_delay_seconds: float | None = None,
    ) -> None:
        settings = get_settings()
        self.cache_dir = cache_dir or settings.project_root / "data" / "cache" / "metadata"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_delay_seconds = (
            min_delay_seconds
            if min_delay_seconds is not None
            else settings.http_min_domain_delay_seconds
        )
        self.user_agent = settings.http_user_agent
        self.timeout_seconds = settings.http_timeout_seconds
        self._last_seen_by_host: dict[str, float] = {}

    def get_json(self, url: str) -> dict[str, Any]:
        validation = validate_url(url)
        cache_path = self.cache_dir / f"{sha256(url.encode('utf-8')).hexdigest()}.json"
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            data = cached.get("data")
            if isinstance(data, dict):
                data.setdefault(
                    "_retrieval",
                    {"source_url": url, "retrieved_at": cached.get("retrieved_at")},
                )
                return data
        self._wait(validation.host)
        import httpx

        response = httpx.get(
            url,
            timeout=self.timeout_seconds,
            headers={"User-Agent": self.user_agent},
        )
        if response.status_code == 429:
            raise SafeFetchError("Metadata API rate-limited the request.")
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Metadata API returned non-object JSON.")
        retrieved_at = datetime.now(UTC).isoformat()
        cache_path.write_text(
            json.dumps({"url": url, "retrieved_at": retrieved_at, "data": data}),
            encoding="utf-8",
        )
        data.setdefault("_retrieval", {"source_url": url, "retrieved_at": retrieved_at})
        return data

    def _wait(self, host: str) -> None:
        if self.min_delay_seconds <= 0:
            return
        now = monotonic()
        last_seen = self._last_seen_by_host.get(host)
        if last_seen is not None:
            remaining = self.min_delay_seconds - (now - last_seen)
            if remaining > 0:
                sleep(remaining)
        self._last_seen_by_host[host] = monotonic()


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


def normalize_openalex_author_id(value: str) -> str:
    match = OPENALEX_AUTHOR_RE.match(value.strip())
    if not match:
        raise ValueError("Enter a valid OpenAlex author ID such as A123 or https://openalex.org/A123.")
    return f"https://openalex.org/{match.group(1).upper()}"


def openalex_author_ids_match(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    try:
        return normalize_openalex_author_id(left) == normalize_openalex_author_id(right)
    except ValueError:
        return False


def normalized_words(value: str | None) -> set[str]:
    return set(TITLE_WORD_RE.findall((value or "").lower()))


def significant_words(value: str | None) -> set[str]:
    ignored = {
        "and",
        "at",
        "department",
        "for",
        "in",
        "institute",
        "laboratory",
        "of",
        "physics",
        "research",
        "school",
        "science",
        "sciences",
        "technology",
        "the",
        "university",
    }
    return {word for word in normalized_words(value) if len(word) > 3 and word not in ignored}


def institution_aliases(value: str | None) -> set[str]:
    aliases = significant_words(value)
    lowered = (value or "").lower()
    if "mit" in lowered or "massachusetts institute of technology" in lowered:
        aliases.update({"mit", "massachusetts"})
    return aliases


def homepage_domain(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    host = parsed.netloc.lower()
    return host.removeprefix("www.") or None


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


def merge_crossref_confirmation(
    openalex_metadata: PublicationMetadata,
    crossref_metadata: PublicationMetadata | None,
) -> PublicationMetadata:
    if crossref_metadata is None:
        return openalex_metadata
    raw = dict(openalex_metadata.raw)
    raw["crossref_confirmation"] = crossref_metadata.raw
    return replace(
        openalex_metadata,
        doi=openalex_metadata.doi or crossref_metadata.doi,
        venue=openalex_metadata.venue or crossref_metadata.venue,
        raw=raw,
    )


class OpenAlexClient:
    base_url = "https://api.openalex.org"

    def __init__(self, client: MetadataClientLike | None = None) -> None:
        self.client = client or HTTPJSONClient()

    def search_authors(self, query: str) -> list[dict[str, Any]]:
        url = f"{self.base_url}/authors?{urlencode({'search': query, 'per-page': '10'})}"
        data = self.client.get_json(url)
        results = data.get("results", [])
        return results if isinstance(results, list) else []

    def search_author_candidates(self, candidate: Candidate) -> list[OpenAlexAuthorCandidate]:
        return rank_openalex_author_candidates(
            candidate,
            [
                score_openalex_author(candidate, item)
                for item in self.search_authors(candidate.full_name)
                if isinstance(item, dict)
            ],
        )

    def works_for_author(
        self,
        openalex_author_id: str,
        *,
        from_year: int | None = None,
    ) -> list[PublicationMetadata]:
        filters = [f"authorships.author.id:{openalex_author_id}"]
        if from_year:
            filters.append(f"from_publication_date:{from_year}-01-01")
        query = {
            "filter": ",".join(filters),
            "sort": "publication_date:desc",
            "per-page": "25",
        }
        url = f"{self.base_url}/works?{urlencode(query)}"
        data = self.client.get_json(url)
        results = data.get("results", [])
        if not isinstance(results, list):
            return []
        return [
            with_retrieval(parse_openalex_work(item), source_url=url)
            for item in results
            if isinstance(item, dict)
        ]


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
        return [
            with_retrieval(parse_crossref_work(item), source_url=url)
            for item in items
            if isinstance(item, dict)
        ]

    def work_by_doi(self, doi: str) -> PublicationMetadata | None:
        normalized = normalize_doi(doi)
        if not normalized:
            return None
        url = f"{self.base_url}/works/{quote(normalized, safe='')}"
        try:
            data = self.client.get_json(url)
        except Exception:
            return None
        message = data.get("message")
        if not isinstance(message, dict):
            return None
        return with_retrieval(parse_crossref_work(message), source_url=url)


def with_retrieval(metadata: PublicationMetadata, *, source_url: str) -> PublicationMetadata:
    raw = dict(metadata.raw)
    raw["_retrieval"] = {
        "source_url": source_url,
        "retrieved_at": datetime.now(UTC).isoformat(),
    }
    return replace(metadata, raw=raw)


def rank_openalex_author_candidates(
    candidate: Candidate,
    author_candidates: list[OpenAlexAuthorCandidate],
) -> list[OpenAlexAuthorCandidate]:
    return sorted(
        author_candidates,
        key=lambda item: (
            item.confidence,
            _topic_overlap_count(candidate, item.topics),
            item.works_count,
        ),
        reverse=True,
    )


def score_openalex_author(candidate: Candidate, item: dict[str, Any]) -> OpenAlexAuthorCandidate:
    display_name = str(item.get("display_name") or "")
    current_institutions = parse_openalex_current_institutions(item)
    previous_institutions = parse_openalex_previous_institutions(item, current_institutions)
    institutions = sorted(set([*current_institutions, *previous_institutions]))
    topics = parse_openalex_author_topics(item)
    profile_url = str(item.get("id") or "") or None
    reasons: list[str] = []
    confidence = 0.0
    if display_name.strip().lower() == candidate.full_name.strip().lower():
        confidence += 0.45
        reasons.append("Exact author-name match.")
    elif candidate.full_name.split()[-1].lower() in display_name.lower():
        confidence += 0.2
        reasons.append("Partial author-name match.")
    if candidate.institution and _institution_matches(candidate.institution, current_institutions):
        confidence += 0.35
        reasons.append(f"Current affiliation matches {candidate.institution}.")
    elif candidate.institution and _institution_matches(
        candidate.institution,
        previous_institutions,
    ):
        confidence += 0.2
        reasons.append(f"Affiliation history includes {candidate.institution}.")
    if candidate.department and _topic_overlap_count(candidate, [*topics, *institutions]) > 0:
        confidence += 0.08
        reasons.append("OpenAlex topics overlap with the candidate department or research area.")
    elif candidate.research_area and _topic_overlap_count(candidate, topics) > 0:
        confidence += 0.06
        reasons.append("OpenAlex topics overlap with the recorded research area.")
    domain = homepage_domain(candidate.official_profile_url)
    if domain and _domain_matches_institution(domain, institutions):
        confidence += 0.05
        reasons.append(f"Homepage domain {domain} matches the affiliation evidence.")
    if candidate.official_profile_url and "profile" in str(item).lower():
        confidence += 0.05
        reasons.append("OpenAlex profile metadata contains profile evidence.")
    raw_works_count = item.get("works_count")
    works_count = raw_works_count if isinstance(raw_works_count, int) else 0
    recent_works_count = parse_openalex_recent_works_count(item)
    if works_count:
        confidence += 0.05
        reasons.append(f"OpenAlex reports {works_count} works.")
    return OpenAlexAuthorCandidate(
        openalex_id=str(item.get("id") or ""),
        display_name=display_name,
        orcid=item.get("orcid") if isinstance(item.get("orcid"), str) else None,
        institutions=institutions,
        works_count=works_count,
        recent_works_count=recent_works_count,
        confidence=min(confidence, 0.95),
        reasons=reasons or ["No strong identity signal."],
        raw=item,
        current_institutions=current_institutions,
        previous_institutions=previous_institutions,
        topics=topics,
        profile_url=profile_url,
    )


def parse_openalex_author_institutions(item: dict[str, Any]) -> list[str]:
    current = parse_openalex_current_institutions(item)
    previous = parse_openalex_previous_institutions(item)
    return sorted(
        set([*current, *previous]),
    )


def parse_openalex_current_institutions(item: dict[str, Any]) -> list[str]:
    institutions: list[str] = []
    values = item.get("last_known_institutions", [])
    if isinstance(values, list):
        for value in values:
            if isinstance(value, dict) and isinstance(value.get("display_name"), str):
                institutions.append(value["display_name"])
    return sorted(set(institutions))


def parse_openalex_previous_institutions(
    item: dict[str, Any],
    current_institutions: list[str] | None = None,
) -> list[str]:
    current = set(current_institutions or parse_openalex_current_institutions(item))
    institutions: list[str] = []
    values = item.get("affiliations", [])
    if isinstance(values, list):
        for value in values:
            if not isinstance(value, dict):
                continue
            institution = value.get("institution")
            if isinstance(institution, dict) and isinstance(institution.get("display_name"), str):
                institutions.append(institution["display_name"])
    return sorted({institution for institution in institutions if institution not in current})


def parse_openalex_author_topics(item: dict[str, Any]) -> list[str]:
    topics: list[str] = []
    for key in ("topics", "x_concepts"):
        values = item.get(key, [])
        if not isinstance(values, list):
            continue
        for value in values[:8]:
            if isinstance(value, dict) and isinstance(value.get("display_name"), str):
                topics.append(value["display_name"])
    return sorted(set(topics))


def parse_openalex_recent_works_count(item: dict[str, Any]) -> int:
    counts = item.get("counts_by_year", [])
    if not isinstance(counts, list):
        return 0
    total = 0
    for count_by_year in counts:
        if not isinstance(count_by_year, dict):
            continue
        year = count_by_year.get("year")
        works_count = count_by_year.get("works_count")
        if isinstance(year, int) and year >= RECENT_YEAR_THRESHOLD and isinstance(works_count, int):
            total += works_count
    return total


def _institution_matches(candidate_institution: str, openalex_institutions: list[str]) -> bool:
    aliases = institution_aliases(candidate_institution)
    if not aliases:
        return False
    for institution in openalex_institutions:
        institution_words = institution_aliases(institution)
        if aliases & institution_words:
            return True
        if candidate_institution.lower() in institution.lower():
            return True
    return False


def _domain_matches_institution(domain: str, institutions: list[str]) -> bool:
    if domain.endswith("mit.edu") and any(
        "massachusetts institute of technology" in institution.lower()
        or "mit" in institution_aliases(institution)
        for institution in institutions
    ):
        return True
    domain_words = significant_words(domain.replace(".", " "))
    return any(domain_words & institution_aliases(institution) for institution in institutions)


def _topic_overlap_count(candidate: Candidate, topics: list[str]) -> int:
    candidate_words = significant_words(candidate.department) | significant_words(
        candidate.research_area,
    )
    if not candidate_words:
        return 0
    topic_words: set[str] = set()
    for topic in topics:
        topic_words.update(significant_words(topic))
    return len(candidate_words & topic_words)


def parse_openalex_work(item: dict[str, Any]) -> PublicationMetadata:
    authorships = item.get("authorships", [])
    authors: list[str] = []
    author_openalex_ids: list[str | None] = []
    institutions: list[str] = []
    corresponding_author_positions: set[int] = set()
    if isinstance(authorships, list):
        for index, authorship in enumerate(authorships, start=1):
            if not isinstance(authorship, dict):
                continue
            author = authorship.get("author", {})
            if isinstance(author, dict) and isinstance(author.get("display_name"), str):
                authors.append(author["display_name"])
                raw_author_id = author.get("id")
                author_openalex_ids.append(
                    raw_author_id if isinstance(raw_author_id, str) else None,
                )
            else:
                author_openalex_ids.append(None)
            if authorship.get("is_corresponding") is True:
                corresponding_author_positions.add(index)
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
        citation_count=int_value(item.get("cited_by_count")),
        work_type=item.get("type") if isinstance(item.get("type"), str) else None,
        abstract_text=parse_openalex_abstract(item.get("abstract_inverted_index")),
        topics=parse_openalex_work_topics(item),
        author_openalex_ids=author_openalex_ids,
        corresponding_author_positions=corresponding_author_positions,
    )


def parse_openalex_abstract(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    positioned: list[tuple[int, str]] = []
    for word, positions in value.items():
        if not isinstance(word, str) or not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int):
                positioned.append((position, word))
    if not positioned:
        return None
    return " ".join(word for _position, word in sorted(positioned))


def int_value(value: object) -> int:
    return value if isinstance(value, int) else 0


def parse_openalex_work_topics(item: dict[str, Any]) -> list[str]:
    topics: list[str] = []
    for key in ("topics", "concepts", "x_concepts"):
        values = item.get(key, [])
        if not isinstance(values, list):
            continue
        for value in values[:10]:
            if isinstance(value, dict) and isinstance(value.get("display_name"), str):
                topics.append(value["display_name"])
    return sorted(set(topics))


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
        citation_count=int_value(item.get("is-referenced-by-count")),
        work_type=item.get("type") if isinstance(item.get("type"), str) else None,
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
    *,
    confirmed_openalex_author_id: str | None = None,
) -> AuthorIdentityMatch:
    normalized_candidate = candidate.full_name.strip().lower()
    author_count = max(len(metadata.authors), len(metadata.author_openalex_ids))
    warnings: list[str] = []
    position = None
    confirmed_author_present = False
    is_corresponding = False
    if confirmed_openalex_author_id:
        normalized_openalex_author_id = normalize_openalex_author_id(confirmed_openalex_author_id)
        for index, author_id in enumerate(metadata.author_openalex_ids, start=1):
            if openalex_author_ids_match(author_id, normalized_openalex_author_id):
                position = index
                confirmed_author_present = True
                is_corresponding = index in metadata.corresponding_author_positions
                break
    if position is None:
        for index, author in enumerate(metadata.authors, start=1):
            if author.strip().lower() == normalized_candidate:
                position = index
                break
        is_corresponding = bool(position and position in metadata.corresponding_author_positions)
    confidence = 0.0
    status = "REVIEW_REQUIRED"
    if confirmed_author_present:
        confidence = 0.95
        status = "MATCHED"
    elif position is not None:
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
        confirmed_author_present=confirmed_author_present,
        is_corresponding=is_corresponding,
        status=status if confidence >= 0.8 else "REVIEW_REQUIRED",
        warnings=warnings,
    )


def score_publication_for_candidate(
    candidate: Candidate,
    metadata: PublicationMetadata,
    match: AuthorIdentityMatch,
    *,
    portfolio_text: str | None = None,
) -> PublicationScore:
    portfolio_unavailable_reason: str | None = None
    if portfolio_text is not None:
        profile_text = portfolio_text
    else:
        portfolio_status = load_research_portfolio_text_status()
        profile_text = portfolio_status.text
        if not portfolio_status.available:
            portfolio_unavailable_reason = portfolio_status.reason
    similarity, overlap_terms = semantic_similarity_to_portfolio(metadata, profile_text)
    score = 0.0
    warnings = list(match.warnings)
    reasons: list[str] = []
    components: dict[str, float] = {}

    if portfolio_unavailable_reason:
        warnings.append(f"PORTFOLIO_INPUT_UNAVAILABLE: {portfolio_unavailable_reason}")
        reasons.append(portfolio_unavailable_reason)
    else:
        semantic_points = round(similarity * 45, 2)
        components["portfolio_similarity"] = semantic_points
        score += semantic_points
    if overlap_terms:
        reasons.append(
            f"Portfolio similarity matched: {', '.join(overlap_terms[:8])}.",
        )
    elif profile_text.strip():
        warnings.append("No strong semantic overlap with the research portfolio.")
        reasons.append("No strong portfolio term overlap was detected.")

    role_points = role_score(match)
    components["confirmed_author_role"] = role_points
    score += role_points
    if match.is_corresponding:
        reasons.append("Confirmed author is marked as corresponding author.")
    elif match.author_position == 1:
        reasons.append("Confirmed author is first author.")
    elif match.author_position == match.author_count and match.author_count > 1:
        reasons.append("Confirmed author is last author.")
    elif match.author_position:
        reasons.append(f"Confirmed author appears at position {match.author_position}.")
    else:
        reasons.append("Confirmed author position is unknown.")

    author_points = author_count_score(match.author_count)
    components["author_count"] = author_points
    score += author_points
    if match.author_count:
        reasons.append(f"Author count: {match.author_count}.")

    if metadata.year and metadata.year >= RECENT_YEAR_THRESHOLD:
        recency_points = recency_score(metadata.year)
        reasons.append(f"Recent publication from {metadata.year}.")
    else:
        recency_points = 0.0
        warnings.append("Publication is outside the default recent-paper window.")
    components["recency"] = recency_points
    score += recency_points

    if metadata.pdf_url or metadata.open_access_url:
        pdf_points = 7.0
        reasons.append("Lawful full text or open-access page is available.")
    else:
        pdf_points = 0.0
    components["lawful_pdf_availability"] = pdf_points
    score += pdf_points

    if is_review_article(metadata):
        review_points = 5.0
        reasons.append("Review article bonus applied.")
    else:
        review_points = 0.0
    components["review_article_bonus"] = review_points
    score += review_points

    citation_points = citation_score(metadata.citation_count)
    components["citation_count"] = citation_points
    score += citation_points
    if metadata.citation_count:
        reasons.append(f"Citation count: {metadata.citation_count}.")

    if match.confidence >= 0.8:
        components["confirmed_author_confidence"] = 3.0
        score += 3.0
    else:
        components["confirmed_author_confidence"] = 0.0
    if portfolio_unavailable_reason:
        connection = "Portfolio input unavailable"
    else:
        connection = ", ".join(overlap_terms[:8]) if overlap_terms else "Needs manual review"
    return PublicationScore(
        score=round(score, 2),
        connection_summary=connection,
        warnings=warnings,
        components=components,
        reasons=reasons,
    )


def role_score(match: AuthorIdentityMatch) -> float:
    if match.is_corresponding:
        return 20.0
    if match.author_position == 1:
        return 16.0
    if match.author_position == match.author_count and match.author_count > 1:
        return 14.0
    if match.author_position:
        return 8.0
    return 0.0


def author_count_score(author_count: int) -> float:
    if author_count <= 0:
        return 0.0
    if author_count <= 3:
        return 10.0
    if author_count <= 8:
        return 7.0
    if author_count <= 20:
        return 4.0
    return 1.0


def recency_score(year: int | None) -> float:
    if year is None:
        return 0.0
    if year >= 2025:
        return 8.0
    if year >= 2023:
        return 6.0
    if year >= RECENT_YEAR_THRESHOLD:
        return 4.0
    return 0.0


def citation_score(citation_count: int) -> float:
    if citation_count <= 0:
        return 0.0
    return round(min(5.0, log10(citation_count + 1) * 1.8), 2)


def is_review_article(metadata: PublicationMetadata) -> bool:
    work_type = (metadata.work_type or "").lower()
    title = metadata.title.lower()
    return work_type == "review" or "review" in title or "survey" in title


def load_research_portfolio_text_status() -> PortfolioTextStatus:
    root = get_settings().project_root
    path = root / PORTFOLIO_PATH
    source_path = str(PORTFOLIO_PATH)
    if not path.exists():
        return PortfolioTextStatus(
            available=False,
            text="",
            status="PORTFOLIO_INPUT_UNAVAILABLE",
            reason=f"Research portfolio PDF is missing at {source_path}.",
            source_path=source_path,
        )
    if not path.is_file():
        return PortfolioTextStatus(
            available=False,
            text="",
            status="PORTFOLIO_INPUT_UNAVAILABLE",
            reason=f"Research portfolio path is not a file: {source_path}.",
            source_path=source_path,
        )
    try:
        with path.open("rb") as file:
            header = file.read(5)
        if header != b"%PDF-":
            return PortfolioTextStatus(
                available=False,
                text="",
                status="PORTFOLIO_INPUT_UNAVAILABLE",
                reason=f"Research portfolio is not a valid PDF: {source_path}.",
                source_path=source_path,
            )
        digest = sha256(path.read_bytes()).hexdigest()
        return _load_research_portfolio_text_status_cached(str(root), digest)
    except Exception as exc:
        return PortfolioTextStatus(
            available=False,
            text="",
            status="PORTFOLIO_INPUT_UNAVAILABLE",
            reason=f"Research portfolio PDF text extraction failed: {exc.__class__.__name__}.",
            source_path=source_path,
        )


@lru_cache(maxsize=8)
def _load_research_portfolio_text_status_cached(
    project_root_value: str,
    portfolio_sha256: str,
) -> PortfolioTextStatus:
    root = Path(project_root_value)
    path = root / PORTFOLIO_PATH
    source_path = str(PORTFOLIO_PATH)
    cache_path = (
        root
        / "data"
        / "cache"
        / "portfolio_text"
        / f"{portfolio_sha256}-{PORTFOLIO_TEXT_EXTRACTION_VERSION}.txt"
    )
    if cache_path.exists():
        cached_text = cache_path.read_text(encoding="utf-8")
        if cached_text.strip():
            return PortfolioTextStatus(
                available=True,
                text=cached_text,
                status="AVAILABLE",
                reason=None,
                source_path=source_path,
                sha256=portfolio_sha256,
                cache_path=str(cache_path.relative_to(root)),
            )
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            return PortfolioTextStatus(
                available=False,
                text="",
                status="PORTFOLIO_INPUT_UNAVAILABLE",
                reason="Research portfolio PDF is encrypted and cannot be extracted.",
                source_path=source_path,
                sha256=portfolio_sha256,
            )
        extracted_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if not extracted_text.strip():
            return PortfolioTextStatus(
                available=False,
                text="",
                status="PORTFOLIO_INPUT_UNAVAILABLE",
                reason="Research portfolio PDF text extraction returned empty text.",
                source_path=source_path,
                sha256=portfolio_sha256,
            )
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(extracted_text, encoding="utf-8")
        return PortfolioTextStatus(
            available=True,
            text=extracted_text,
            status="AVAILABLE",
            reason=None,
            source_path=source_path,
            sha256=portfolio_sha256,
            cache_path=str(cache_path.relative_to(root)),
        )
    except Exception as exc:
        return PortfolioTextStatus(
            available=False,
            text="",
            status="PORTFOLIO_INPUT_UNAVAILABLE",
            reason=f"Research portfolio PDF text extraction failed: {exc.__class__.__name__}.",
            source_path=source_path,
            sha256=portfolio_sha256,
        )


def clear_research_portfolio_text_cache() -> None:
    _load_research_portfolio_text_status_cached.cache_clear()


def load_research_portfolio_text() -> str:
    return load_research_portfolio_text_status().text


def require_research_portfolio_text() -> str:
    status = load_research_portfolio_text_status()
    if not status.available:
        raise PortfolioInputUnavailable(status.reason or "Research portfolio text is unavailable.")
    return status.text


def semantic_similarity_to_portfolio(
    metadata: PublicationMetadata,
    portfolio_text: str,
) -> tuple[float, list[str]]:
    publication_text = " ".join(
        [
            metadata.title,
            metadata.abstract_text or "",
            " ".join(metadata.topics),
            metadata.venue or "",
        ],
    )
    publication_weights = term_weights(publication_text)
    portfolio_weights = term_weights(portfolio_text)
    if not publication_weights or not portfolio_weights:
        return 0.0, []
    shared = sorted(
        set(publication_weights) & set(portfolio_weights),
        key=lambda term: publication_weights[term] + portfolio_weights[term],
        reverse=True,
    )
    dot = sum(publication_weights[term] * portfolio_weights[term] for term in shared)
    publication_norm = sqrt(sum(value * value for value in publication_weights.values()))
    portfolio_norm = sqrt(sum(value * value for value in portfolio_weights.values()))
    if publication_norm == 0 or portfolio_norm == 0:
        return 0.0, []
    return min(1.0, dot / (publication_norm * portfolio_norm)), shared


def term_weights(text: str) -> dict[str, float]:
    weights: dict[str, float] = {}
    for word in TITLE_WORD_RE.findall(text.lower()):
        if len(word) <= 4:
            continue
        if word in {"paper", "using", "based", "study", "analysis", "research", "model"}:
            continue
        weights[word] = weights.get(word, 0.0) + 1.0
    return weights


def upsert_publication_with_authorship(
    session: Session,
    *,
    candidate: Candidate,
    metadata: PublicationMetadata,
    confirmed_openalex_author_id: str | None = None,
    portfolio_text: str | None = None,
) -> tuple[Publication, Authorship]:
    fingerprint = title_fingerprint(metadata.title)
    metadata_author_count = max(len(metadata.authors), len(metadata.author_openalex_ids))
    match_conditions = [Publication.title_fingerprint == fingerprint]
    if metadata.doi:
        match_conditions.append(Publication.doi == metadata.doi)
    if metadata.arxiv_id:
        match_conditions.append(Publication.arxiv_id == metadata.arxiv_id)
    if metadata.openalex_id:
        match_conditions.append(Publication.openalex_id == metadata.openalex_id)
    publication = session.scalars(
        select(Publication).where(or_(*match_conditions)),
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
            author_count=metadata_author_count or None,
            citation_count=metadata.citation_count,
            work_type=metadata.work_type,
            metadata_json=json.dumps(metadata.raw),
        )
        session.add(publication)
        session.flush()
    else:
        publication.citation_count = max(publication.citation_count, metadata.citation_count)
        publication.work_type = publication.work_type or metadata.work_type
        publication.author_count = publication.author_count or metadata_author_count or None
    match = match_candidate_author(
        candidate,
        metadata,
        confirmed_openalex_author_id=confirmed_openalex_author_id,
    )
    scored = score_publication_for_candidate(
        candidate,
        metadata,
        match,
        portfolio_text=portfolio_text,
    )
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
    authorship.role = authorship_role(
        match.author_position,
        match.author_count,
        corresponding=match.is_corresponding,
    )
    if confirmed_openalex_author_id:
        authorship.openalex_author_id = normalize_openalex_author_id(confirmed_openalex_author_id)
    authorship.confirmed_author_present = match.confirmed_author_present
    authorship.corresponding_author = match.is_corresponding
    authorship.identity_confidence = match.confidence
    authorship.match_status = match.status
    authorship.score = scored.score
    authorship.connection_summary = scored.connection_summary
    authorship.warnings_json = json.dumps(scored.warnings)
    authorship.score_details_json = json.dumps(
        {
            "components": scored.components,
            "reasons": scored.reasons,
        },
    )
    return publication, authorship


def get_authorship(
    session: Session,
    *,
    candidate_id: int,
    publication_id: int,
) -> Authorship | None:
    return session.scalars(
        select(Authorship).where(
            Authorship.candidate_id == candidate_id,
            Authorship.publication_id == publication_id,
        ),
    ).first()


def approve_publication_for_retrieval(
    session: Session,
    *,
    candidate_id: int,
    publication_id: int,
    notes: str | None = None,
) -> Authorship:
    authorship = get_authorship(
        session,
        candidate_id=candidate_id,
        publication_id=publication_id,
    )
    if authorship is None:
        raise ValueError("Candidate is not linked to this publication.")
    authorship.selected_for_retrieval = True
    authorship.selected_at = datetime.now(UTC)
    authorship.selection_notes = notes.strip() if notes else None
    session.add(authorship)
    return authorship


def assert_publication_selected_for_retrieval(
    session: Session,
    *,
    candidate_id: int,
    publication_id: int,
) -> None:
    authorship = get_authorship(
        session,
        candidate_id=candidate_id,
        publication_id=publication_id,
    )
    if authorship is None or not authorship.selected_for_retrieval:
        raise ValueError("Approve this paper before PDF retrieval or analysis.")


def candidate_has_publications_for_openalex_author(
    session: Session,
    *,
    candidate_id: int,
    openalex_author_id: str,
) -> bool:
    normalized_author_id = normalize_openalex_author_id(openalex_author_id)
    return (
        session.scalars(
            select(Authorship.id).where(
                Authorship.candidate_id == candidate_id,
                Authorship.openalex_author_id == normalized_author_id,
            ),
        ).first()
        is not None
    )


def full_text_label(publication: Publication) -> str:
    if publication.pdf_url and publication.arxiv_id:
        return "PDF URL and arXiv available"
    if publication.pdf_url:
        return "PDF URL available"
    if publication.arxiv_id:
        return "arXiv PDF available"
    if publication.open_access_url:
        return "Open-access landing page only"
    return "No lawful full text recorded"


def list_openalex_author_candidates_for_candidate(
    candidate: Candidate,
    *,
    openalex: OpenAlexClient | None = None,
) -> list[OpenAlexAuthorCandidate]:
    openalex_client = openalex or OpenAlexClient()
    return rank_openalex_author_candidates(
        candidate,
        openalex_client.search_author_candidates(candidate),
    )


def retrieve_recent_publications_for_candidate(
    session: Session,
    *,
    candidate: Candidate,
    openalex: OpenAlexClient | None = None,
    crossref: CrossrefClient | None = None,
    from_year: int = RECENT_YEAR_THRESHOLD,
    min_author_confidence: float = 0.75,
    confirmed_openalex_author_id: str | None = None,
) -> PublicationRetrievalResult:
    openalex_client = openalex or OpenAlexClient()
    crossref_client = crossref or CrossrefClient()
    stored_openalex_author_id = candidate.openalex_author_id
    selected_openalex_author_id = confirmed_openalex_author_id or stored_openalex_author_id
    if selected_openalex_author_id:
        author = OpenAlexAuthorCandidate(
            openalex_id=normalize_openalex_author_id(selected_openalex_author_id),
            display_name=candidate.full_name,
            orcid=None,
            institutions=[candidate.institution] if candidate.institution else [],
            works_count=0,
            recent_works_count=0,
            confidence=1.0,
            reasons=["Confirmed OpenAlex author ID stored for this candidate."],
            raw={"manual_confirmation": True},
        )
    else:
        author_candidates = list_openalex_author_candidates_for_candidate(
            candidate,
            openalex=openalex_client,
        )
        if not author_candidates:
            raise ValueError("No OpenAlex author candidates found.")
        author_candidates = rank_openalex_author_candidates(candidate, author_candidates)
        author = author_candidates[0]
        if not author.openalex_id or author.confidence < min_author_confidence:
            options = "; ".join(
                f"{item.display_name} ({item.confidence:.2f}, {item.openalex_id})"
                for item in author_candidates[:3]
            )
            raise ValueError(f"OpenAlex author identity requires manual confirmation: {options}")

    works = openalex_client.works_for_author(author.openalex_id, from_year=from_year)
    merged: list[PublicationMetadata] = []
    messages = [
        f"OpenAlex author selected: {author.display_name} ({author.confidence:.2f}).",
        *author.reasons,
    ]
    for metadata in works:
        crossref_metadata = crossref_client.work_by_doi(metadata.doi) if metadata.doi else None
        merged.append(merge_crossref_confirmation(metadata, crossref_metadata))
    deduped = deduplicate_metadata(merged)
    portfolio_status = load_research_portfolio_text_status()
    portfolio_text = portfolio_status.text if portfolio_status.available else None
    authorship_ids: set[int] = set()
    review_required_ids: set[int] = set()
    for metadata in deduped:
        _publication, authorship = upsert_publication_with_authorship(
            session,
            candidate=candidate,
            metadata=metadata,
            confirmed_openalex_author_id=author.openalex_id,
            portfolio_text=portfolio_text,
        )
        session.flush()
        authorship_ids.add(authorship.id)
        if authorship.match_status == "REVIEW_REQUIRED":
            review_required_ids.add(authorship.id)
    skipped_count = max(0, len(works) - len(authorship_ids))
    return PublicationRetrievalResult(
        author=author,
        imported_count=len(authorship_ids),
        review_required_count=len(review_required_ids),
        skipped_count=skipped_count,
        messages=messages,
    )


def manual_publication_metadata(
    *,
    title: str,
    year: int | None,
    venue: str | None,
    doi: str | None,
    arxiv_id: str | None,
    open_access_url: str | None,
    pdf_url: str | None,
    authors_text: str,
    scholar_url: str | None,
) -> PublicationMetadata:
    authors = [author.strip() for author in authors_text.split(",") if author.strip()]
    raw = {"entry_mode": "manual"}
    if scholar_url:
        raw["scholar_url"] = scholar_url
    return PublicationMetadata(
        title=title.strip(),
        year=year,
        venue=venue.strip() or None if venue else None,
        doi=normalize_doi(doi),
        arxiv_id=arxiv_id.strip().lower() or None if arxiv_id else None,
        openalex_id=None,
        source="manual_scholar" if scholar_url else "manual",
        open_access_url=open_access_url.strip() or None if open_access_url else None,
        pdf_url=pdf_url.strip() or None if pdf_url else None,
        authors=authors,
        author_institutions=[],
        raw=raw,
    )


def list_candidate_publications(
    session: Session,
    candidate_id: int,
    *,
    sort: str = "best",
) -> list[tuple[Authorship, Publication]]:
    order_by = publication_sort_order(sort)
    rows = session.execute(
        select(Authorship, Publication)
        .join(Publication, Publication.id == Authorship.publication_id)
        .where(Authorship.candidate_id == candidate_id)
        .order_by(*order_by),
    )
    return [(authorship, publication) for authorship, publication in rows.all()]


def publication_sort_order(sort: str) -> list[Any]:
    base: list[Any] = [Authorship.selected_for_retrieval.desc()]
    if sort == "newest":
        return [
            *base,
            Publication.year.desc().nullslast(),
            Authorship.score.desc(),
        ]
    if sort == "citations":
        return [
            *base,
            Publication.citation_count.desc(),
            Authorship.score.desc(),
        ]
    if sort == "fewest_authors":
        return [
            *base,
            Authorship.author_count.asc().nullslast(),
            Authorship.score.desc(),
        ]
    return [
        *base,
        Authorship.score.desc(),
        Publication.year.desc().nullslast(),
    ]


def list_candidate_publication_reviews(
    session: Session,
    candidate_id: int,
    *,
    sort: str = "best",
) -> list[CandidatePublicationReview]:
    reviews: list[CandidatePublicationReview] = []
    for authorship, publication in list_candidate_publications(session, candidate_id, sort=sort):
        warnings = json.loads(authorship.warnings_json or "[]")
        if not isinstance(warnings, list):
            warnings = []
        score_details = json.loads(authorship.score_details_json or "{}")
        if not isinstance(score_details, dict):
            score_details = {}
        raw_components = score_details.get("components", {})
        components = (
            {str(key): float(value) for key, value in raw_components.items()}
            if isinstance(raw_components, dict)
            else {}
        )
        raw_reasons = score_details.get("reasons", [])
        reasons = [str(reason) for reason in raw_reasons] if isinstance(raw_reasons, list) else []
        reviews.append(
            CandidatePublicationReview(
                authorship=authorship,
                publication=publication,
                warnings=[str(warning) for warning in warnings],
                score_components=components,
                score_reasons=reasons,
                full_text_label=full_text_label(publication),
                full_text_available=bool(publication.pdf_url or publication.arxiv_id),
            ),
        )
    return reviews


def list_publications(session: Session) -> list[Publication]:
    return list(session.scalars(select(Publication).order_by(Publication.created_at.desc())))


def authorship_role(
    position: int | None,
    author_count: int,
    *,
    corresponding: bool = False,
) -> str | None:
    if position is None:
        return None
    if corresponding:
        return "corresponding_author"
    if position == 1:
        return "first_author"
    if position == author_count and author_count > 1:
        return "last_author"
    if author_count > LARGE_AUTHOR_WARNING_THRESHOLD:
        return "large_consortium"
    return "coauthor"
