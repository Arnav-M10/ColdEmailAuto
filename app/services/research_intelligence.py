import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
from math import sqrt
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.candidate import Candidate
from app.models.intelligence import ResearcherProfile
from app.models.publication import Authorship, Publication
from app.services.metadata import list_candidate_publications
from app.services.retrieval import pdf_eligibility_for_publication

RESEARCHER_PROFILE_PROMPT_VERSION = "researcher-profile-v1"
GENERIC_TERMS = {
    "analysis",
    "research",
    "study",
    "paper",
    "data",
    "using",
    "method",
    "methods",
    "model",
    "models",
    "results",
}


@dataclass(frozen=True)
class ProfileView:
    themes: list[dict[str, object]]
    clusters: list[dict[str, object]]
    methods: list[str]
    datasets: list[str]
    techniques: list[str]
    collaborators: list[str]
    active_projects: list[dict[str, object]]
    portfolio_connections: list[dict[str, object]]
    evidence: list[dict[str, object]]
    papers_analyzed: list[dict[str, object]]
    recent_direction: str | None
    balance: str | None
    confidence: float


@dataclass(frozen=True)
class EmailUsefulness:
    score: float
    reasons: list[str]
    rejections: list[str]
    represents_broader_theme: bool


PORTFOLIO_AREAS: dict[str, dict[str, object]] = {
    "Regge spectral geometry and random matrix theory": {
        "terms": {
            "regge",
            "spectral",
            "geometry",
            "curvature",
            "triangulated",
            "laplace",
            "beltrami",
            "eigenvalue",
            "eigenvector",
            "heat",
            "trace",
            "dimension",
            "statistics",
            "goe",
            "poisson",
            "mathematica",
        },
        "help": "symbolic checks, spectral computations, and numerical experiments",
    },
    "Parker Solar Probe persistent homology": {
        "terms": {
            "magnetic",
            "field",
            "fields",
            "time",
            "series",
            "persistent",
            "homology",
            "topological",
            "intermittency",
            "pvi",
            "bootstrap",
            "solar",
            "wind",
            "python",
        },
        "help": "scientific Python, time-series analysis, bootstrap checks, and visualization",
    },
    "Asteroid orbit determination": {
        "terms": {
            "orbit",
            "orbital",
            "mechanics",
            "monte",
            "carlo",
            "uncertainty",
            "covariance",
            "moid",
            "convergence",
            "sensitivity",
            "asteroid",
        },
        "help": "Monte Carlo uncertainty propagation and sensitivity analysis",
    },
    "Stochastic optimization": {
        "terms": {
            "stochastic",
            "optimization",
            "convex",
            "uncertainty",
            "sample",
            "average",
            "approximation",
            "numerical",
        },
        "help": "numerical optimization and uncertainty checks",
    },
}

METHOD_TERMS = {
    "simulation",
    "simulations",
    "spectroscopy",
    "photometry",
    "survey",
    "surveys",
    "optimization",
    "monte carlo",
    "bootstrap",
    "persistent homology",
    "numerical",
    "statistical",
    "machine learning",
    "time-series",
    "time series",
}
DATASET_TERMS = {
    "parker solar probe",
    "gaia",
    "ztf",
    "kepler",
    "tess",
    "desi",
    "sdss",
    "lsst",
    "hst",
    "jwst",
    "chandra",
    "alma",
}


def build_or_reuse_researcher_profile(
    session: Session,
    *,
    candidate: Candidate,
    provider: str = "deterministic",
    model: str = "local-text-similarity",
) -> ResearcherProfile:
    version = publication_metadata_version(session, candidate.id)
    cache_key = researcher_profile_cache_key(candidate.id, version, provider, model)
    cached = session.scalars(
        select(ResearcherProfile)
        .where(ResearcherProfile.cache_key == cache_key)
        .order_by(ResearcherProfile.created_at.desc()),
    ).first()
    if cached is not None:
        return cached
    view = synthesize_researcher_profile(session, candidate=candidate)
    profile = ResearcherProfile(
        candidate_id=candidate.id,
        cache_key=cache_key,
        provider=provider,
        model=model,
        prompt_version=RESEARCHER_PROFILE_PROMPT_VERSION,
        publication_metadata_version=version,
        papers_analyzed_json=json.dumps(view.papers_analyzed),
        themes_json=json.dumps(view.themes),
        clusters_json=json.dumps(view.clusters),
        methods_json=json.dumps(view.methods),
        datasets_json=json.dumps(view.datasets),
        techniques_json=json.dumps(view.techniques),
        collaborators_json=json.dumps(view.collaborators),
        active_projects_json=json.dumps(view.active_projects),
        portfolio_connections_json=json.dumps(view.portfolio_connections),
        recent_direction=view.recent_direction,
        balance=view.balance,
        evidence_json=json.dumps(view.evidence),
        confidence=view.confidence,
    )
    session.add(profile)
    session.flush()
    return profile


def synthesize_researcher_profile(session: Session, *, candidate: Candidate) -> ProfileView:
    rows = list_candidate_publications(session, candidate.id, sort="newest")[:20]
    paper_views = [
        publication_context(authorship, publication) for authorship, publication in rows
    ]
    texts = [str(item["text"]) for item in paper_views]
    combined = " ".join(texts)
    theme_counts = score_portfolio_areas(combined)
    themes: list[dict[str, object]] = []
    for label, score in theme_counts:
        if score > 0:
            themes.append(
                {
                    "label": label,
                    "classification": "VERIFIED" if score >= 3 else "STRONG_INFERENCE",
                    "support": score,
                },
            )
    themes = themes[:6]
    clusters = cluster_publications(paper_views)
    methods = top_terms(combined, METHOD_TERMS)
    datasets = top_terms(combined, DATASET_TERMS)
    extra_terms = [term for term in top_keywords(combined, 12) if term not in methods]
    techniques = sorted(set(methods + extra_terms))[:10]
    collaborators = recurring_collaborators(paper_views, candidate.full_name)
    active_projects = infer_active_projects(clusters)
    portfolio_connections = [
        {
            "area": label,
            "classification": "VERIFIED" if score >= 3 else "STRONG_INFERENCE",
            "connection": PORTFOLIO_AREAS[label]["help"],
            "support": score,
        }
        for label, score in theme_counts
        if score > 0
    ][:4]
    evidence = [
        {
            "classification": "VERIFIED",
            "source": str(item["title"]),
            "year": item["year"],
            "excerpt": str(item["text"])[:220],
        }
        for item in paper_views[:8]
    ]
    confidence = min(0.95, 0.35 + len(paper_views) * 0.03 + len(themes) * 0.06)
    return ProfileView(
        themes=themes,
        clusters=clusters,
        methods=methods,
        datasets=datasets,
        techniques=techniques,
        collaborators=collaborators,
        active_projects=active_projects,
        portfolio_connections=portfolio_connections,
        evidence=evidence,
        papers_analyzed=[
            {
                "publication_id": item["publication_id"],
                "title": item["title"],
                "year": item["year"],
            }
            for item in paper_views
        ],
        recent_direction=recent_direction_from_clusters(clusters),
        balance=research_balance(combined),
        confidence=round(confidence, 2),
    )


def email_usefulness_for_publication(
    *,
    publication: Publication,
    authorship: Authorship,
    profile: ResearcherProfile | None,
) -> EmailUsefulness:
    text = publication_text(publication)
    portfolio_scores = score_portfolio_areas(text)
    best_portfolio = portfolio_scores[0] if portfolio_scores else ("", 0)
    score = 0.0
    reasons: list[str] = []
    rejections: list[str] = []
    eligibility = pdf_eligibility_for_publication(publication)
    if eligibility.eligible:
        score += 20
        reasons.append(f"Lawful full text is available: {eligibility.source_type}.")
    else:
        rejections.append(eligibility.rejection_reason or "No usable lawful full text.")
    if authorship.role in {"first_author", "last_author", "corresponding_author"}:
        score += 18
        reasons.append(f"Candidate role is {authorship.role.replace('_', ' ')}.")
    if authorship.author_count and authorship.author_count <= 8:
        score += 10
        reasons.append("Author count is manageable for attribution.")
    if publication.year and publication.year >= 2023:
        score += 10
        reasons.append("Paper is recent enough to represent current work.")
    if best_portfolio[1] >= 2:
        score += min(22, best_portfolio[1] * 5)
        reasons.append(f"Portfolio connection: {best_portfolio[0]}.")
    elif keyword_set(text) <= GENERIC_TERMS:
        rejections.append("Match is only through generic words.")
    if top_terms(text, METHOD_TERMS):
        score += 10
        reasons.append("Paper has a clear technical method useful for outreach.")
    represents_theme = represents_profile_theme(publication, profile)
    if represents_theme:
        score += 10
        reasons.append("Paper represents a broader recent research theme.")
    else:
        reasons.append("Broader-theme support is weak and should be reviewed.")
    if authorship.author_count and authorship.author_count > 25:
        rejections.append("Consortium-scale author list makes contribution unclear.")
    return EmailUsefulness(
        score=round(score, 2),
        reasons=reasons,
        rejections=rejections,
        represents_broader_theme=represents_theme,
    )


def profile_view(profile: ResearcherProfile | None) -> ProfileView | None:
    if profile is None:
        return None
    return ProfileView(
        themes=json_list(profile.themes_json),
        clusters=json_list(profile.clusters_json),
        methods=[str(item) for item in json_list(profile.methods_json)],
        datasets=[str(item) for item in json_list(profile.datasets_json)],
        techniques=[str(item) for item in json_list(profile.techniques_json)],
        collaborators=[str(item) for item in json_list(profile.collaborators_json)],
        active_projects=json_list(profile.active_projects_json),
        portfolio_connections=json_list(profile.portfolio_connections_json),
        evidence=json_list(profile.evidence_json),
        papers_analyzed=json_list(profile.papers_analyzed_json),
        recent_direction=profile.recent_direction,
        balance=profile.balance,
        confidence=profile.confidence,
    )


def publication_metadata_version(session: Session, candidate_id: int) -> str:
    rows = list_candidate_publications(session, candidate_id, sort="newest")
    payload = [
        {
            "publication_id": publication.id,
            "title": publication.title,
            "year": publication.year,
            "metadata": publication.metadata_json,
            "updated_at": publication.updated_at.isoformat(),
            "authorship_score": authorship.score,
        }
        for authorship, publication in rows[:20]
    ]
    return sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def researcher_profile_cache_key(
    candidate_id: int,
    metadata_version: str,
    provider: str,
    model: str,
) -> str:
    raw = (
        f"{candidate_id}:{metadata_version}:"
        f"{RESEARCHER_PROFILE_PROMPT_VERSION}:{provider}:{model}"
    )
    return sha256(raw.encode("utf-8")).hexdigest()


def latest_researcher_profile(session: Session, candidate_id: int) -> ResearcherProfile | None:
    return session.scalars(
        select(ResearcherProfile)
        .where(ResearcherProfile.candidate_id == candidate_id)
        .order_by(ResearcherProfile.created_at.desc()),
    ).first()


def publication_context(authorship: Authorship, publication: Publication) -> dict[str, object]:
    raw = json_object(publication.metadata_json)
    text = publication_text(publication)
    return {
        "publication_id": publication.id,
        "title": publication.title,
        "year": publication.year,
        "authorship_role": authorship.role,
        "text": text,
        "authors": raw_authors(raw),
    }


def publication_text(publication: Publication) -> str:
    raw = json_object(publication.metadata_json)
    parts = [
        publication.title,
        publication.venue or "",
        publication.work_type or "",
        abstract_from_raw(raw),
        " ".join(topics_from_raw(raw)),
    ]
    return " ".join(part for part in parts if part).lower()


def abstract_from_raw(raw: dict[str, Any]) -> str:
    direct = raw.get("abstract") or raw.get("abstract_text")
    if isinstance(direct, str):
        return direct
    inverted = raw.get("abstract_inverted_index")
    if not isinstance(inverted, dict):
        return ""
    positioned: dict[int, str] = {}
    for word, positions in inverted.items():
        if isinstance(word, str) and isinstance(positions, list):
            for position in positions:
                if isinstance(position, int):
                    positioned[position] = word
    return " ".join(positioned[index] for index in sorted(positioned))


def topics_from_raw(raw: dict[str, Any]) -> list[str]:
    topics = raw.get("topics")
    if not isinstance(topics, list):
        return []
    values: list[str] = []
    for topic in topics:
        if isinstance(topic, dict):
            value = topic.get("display_name")
            if isinstance(value, str):
                values.append(value)
        elif isinstance(topic, str):
            values.append(topic)
    return values


def raw_authors(raw: dict[str, Any]) -> list[str]:
    authorships = raw.get("authorships")
    if not isinstance(authorships, list):
        return []
    authors: list[str] = []
    for authorship in authorships:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author")
        if isinstance(author, dict) and isinstance(author.get("display_name"), str):
            authors.append(str(author["display_name"]))
    return authors


def score_portfolio_areas(text: str) -> list[tuple[str, int]]:
    terms = keyword_set(text)
    scores = []
    for label, details in PORTFOLIO_AREAS.items():
        area_terms = cast(set[str], details["terms"])
        scores.append((label, len(terms & area_terms)))
    return sorted(scores, key=lambda item: item[1], reverse=True)


def keyword_set(text: str) -> set[str]:
    cleaned = "".join(char.lower() if char.isalnum() else " " for char in text)
    tokens = {token for token in cleaned.split() if len(token) > 3}
    phrases = {phrase for phrase in METHOD_TERMS | DATASET_TERMS if phrase in text.lower()}
    return tokens | phrases


def top_terms(text: str, allowed: set[str]) -> list[str]:
    lowered = text.lower()
    return sorted(term for term in allowed if term in lowered)


def top_keywords(text: str, count: int) -> list[str]:
    words = [word for word in keyword_set(text) if word not in GENERIC_TERMS]
    counts = Counter(words)
    return [word for word, _count in counts.most_common(count)]


def cluster_publications(papers: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for paper in papers:
        scores = score_portfolio_areas(str(paper["text"]))
        label, score = scores[0] if scores else ("General research", 0)
        grouped[label if score > 0 else "General research"].append(paper)
    clusters: list[dict[str, object]] = []
    for label, items in grouped.items():
        text = " ".join(str(item["text"]) for item in items)
        years = [item["year"] for item in items if isinstance(item["year"], int)]
        representative = [str(item["title"]) for item in items[:4]]
        clusters.append(
            {
                "name": label,
                "representative_papers": representative,
                "years": sorted(set(years), reverse=True),
                "common_methods": top_terms(text, METHOD_TERMS),
                "connection_to_portfolio": PORTFOLIO_AREAS.get(label, {}).get("help", ""),
                "confidence": min(0.9, 0.45 + len(items) * 0.08),
            },
        )
    return sorted(
        clusters,
        key=lambda item: len(cast(list[object], item["representative_papers"])),
        reverse=True,
    )


def recurring_collaborators(papers: list[dict[str, object]], candidate_name: str) -> list[str]:
    counts: Counter[str] = Counter()
    candidate_lower = candidate_name.lower()
    for paper in papers:
        authors = paper.get("authors", [])
        if not isinstance(authors, list):
            continue
        for author in authors:
            if isinstance(author, str) and author.lower() != candidate_lower:
                counts[author] += 1
    return [author for author, count in counts.most_common(8) if count >= 2]


def infer_active_projects(clusters: list[dict[str, object]]) -> list[dict[str, object]]:
    projects = []
    for cluster in clusters[:4]:
        years = cluster.get("years", [])
        if not isinstance(years, list):
            years = []
        recent = any(isinstance(year, int) and year >= 2023 for year in years)
        projects.append(
            {
                "project": cluster["name"],
                "classification": "STRONG_INFERENCE" if recent else "SPECULATIVE",
                "support": cluster["representative_papers"],
            },
        )
    return projects


def recent_direction_from_clusters(clusters: list[dict[str, object]]) -> str | None:
    if not clusters:
        return None
    names = [str(cluster["name"]) for cluster in clusters[:2]]
    return "Recent publications concentrate on " + " and ".join(names) + "."


def research_balance(text: str) -> str:
    lowered = text.lower()
    scores = {
        "observational": sum(term in lowered for term in ["observ", "survey", "telescope"]),
        "computational": sum(term in lowered for term in ["simulation", "numerical", "python"]),
        "theoretical": sum(term in lowered for term in ["theorem", "theory", "analytical"]),
        "experimental": sum(term in lowered for term in ["experiment", "laboratory"]),
    }
    top = [label for label, score in scores.items() if score == max(scores.values()) and score > 0]
    return ", ".join(top).title() if top else "Not enough metadata to classify"


def represents_profile_theme(publication: Publication, profile: ResearcherProfile | None) -> bool:
    if profile is None:
        return False
    text_terms = keyword_set(publication_text(publication))
    view = profile_view(profile)
    if view is None:
        return False
    for cluster in view.clusters:
        if not isinstance(cluster, dict):
            continue
        name = str(cluster.get("name", "")).lower()
        if keyword_set(name) & text_terms:
            return True
    return False


def cosine_similarity(text_a: str, text_b: str) -> float:
    counts_a = Counter(keyword_set(text_a))
    counts_b = Counter(keyword_set(text_b))
    shared = set(counts_a) & set(counts_b)
    numerator = sum(counts_a[key] * counts_b[key] for key in shared)
    norm_a = sqrt(sum(value * value for value in counts_a.values()))
    norm_b = sqrt(sum(value * value for value in counts_b.values()))
    if not norm_a or not norm_b:
        return 0.0
    return numerator / (norm_a * norm_b)


def json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def json_list(value: str) -> list[Any]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []
