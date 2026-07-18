import json
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from time import monotonic, sleep
from typing import Any, Protocol
from urllib.parse import quote, urlencode, urlparse

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.candidate import Candidate
from app.models.publication import Authorship, Publication
from app.services.web_safety import SafeFetchError, validate_url

TITLE_WORD_RE = re.compile(r"[a-z0-9]+")
ARXIV_RE = re.compile(r"arxiv[:/ ]+([0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?)", re.I)
DOI_PREFIX_RE = re.compile(r"^https?://(?:dx\.)?doi\.org/", re.I)
OPENALEX_AUTHOR_RE = re.compile(r"^(?:https://openalex\.org/)?(A[0-9]+)$", re.I)
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
    authorship_ids: set[int] = set()
    review_required_ids: set[int] = set()
    for metadata in deduped:
        _publication, authorship = upsert_publication_with_authorship(
            session,
            candidate=candidate,
            metadata=metadata,
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
) -> list[tuple[Authorship, Publication]]:
    rows = session.execute(
        select(Authorship, Publication)
        .join(Publication, Publication.id == Authorship.publication_id)
        .where(Authorship.candidate_id == candidate_id)
        .order_by(
            Authorship.selected_for_retrieval.desc(),
            Authorship.score.desc(),
            Publication.year.desc().nullslast(),
        ),
    )
    return [(authorship, publication) for authorship, publication in rows.all()]


def list_candidate_publication_reviews(
    session: Session,
    candidate_id: int,
) -> list[CandidatePublicationReview]:
    reviews: list[CandidatePublicationReview] = []
    for authorship, publication in list_candidate_publications(session, candidate_id):
        warnings = json.loads(authorship.warnings_json or "[]")
        if not isinstance(warnings, list):
            warnings = []
        reviews.append(
            CandidatePublicationReview(
                authorship=authorship,
                publication=publication,
                warnings=[str(warning) for warning in warnings],
                full_text_label=full_text_label(publication),
                full_text_available=bool(publication.pdf_url or publication.arxiv_id),
            ),
        )
    return reviews


def list_publications(session: Session) -> list[Publication]:
    return list(session.scalars(select(Publication).order_by(Publication.created_at.desc())))


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
