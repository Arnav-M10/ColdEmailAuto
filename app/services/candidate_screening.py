import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.candidate import Candidate, CandidateStatus

ARNAV_RESEARCH_AREAS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "spectral geometry and Regge calculus",
        (
            "regge",
            "spectral geometry",
            "laplace",
            "laplace-beltrami",
            "eigenvalue",
            "heat trace",
            "spectral dimension",
            "random matrix",
            "matrix theory",
            "quantum gravity",
            "geometry",
        ),
        "Matches Regge/spectral-geometry interests.",
    ),
    (
        "Parker Solar Probe and topological time-series analysis",
        (
            "parker solar probe",
            "solar wind",
            "magnetic field",
            "time series",
            "persistent homology",
            "topological data",
            "intermittency",
            "pvi",
            "plasma",
            "heliosphere",
        ),
        "Matches Parker Solar Probe, plasma, or topological time-series work.",
    ),
    (
        "orbit determination and Monte Carlo uncertainty",
        (
            "orbit determination",
            "asteroid",
            "minor planet",
            "moid",
            "monte carlo",
            "covariance",
            "uncertainty propagation",
            "sensitivity analysis",
            "celestial mechanics",
        ),
        "Matches orbit determination, uncertainty, or Monte Carlo background.",
    ),
    (
        "stochastic optimization and uncertainty modeling",
        (
            "stochastic optimization",
            "convex",
            "optimization",
            "uncertainty",
            "sample-average",
            "probabilistic",
            "numerical",
            "data analysis",
        ),
        "Matches stochastic optimization, uncertainty, or numerical modeling.",
    ),
)

COMPUTATIONAL_TERMS = {
    "computational",
    "simulation",
    "numerical",
    "data",
    "software",
    "modeling",
    "python",
    "algorithm",
    "statistical",
    "machine learning",
    "theory",
    "theoretical",
    "mathematical",
}
MENTORING_TERMS = {"student", "students", "undergraduate", "mentor", "group", "lab"}
EXPERIMENTAL_TERMS = {
    "apparatus",
    "detector",
    "experimental",
    "hardware",
    "instrument",
    "instrumentation",
    "laboratory equipment",
    "fabrication",
}
INACTIVE_TERMS = {"emeritus", "emerita", "retired", "in memoriam", "former professor"}
CONTACTED_STATUSES = {
    CandidateStatus.SENT,
    CandidateStatus.REPLIED,
    CandidateStatus.FOLLOW_UP_DUE,
    CandidateStatus.DECLINED,
    CandidateStatus.CLOSED,
}
GROUP_NAME_RE = re.compile(
    r"\b((?:[A-Z][A-Za-z&'.-]+\s){1,5}(?:Group|Lab|Laboratory|Center|Institute))\b",
)


@dataclass(frozen=True)
class ScreeningContext:
    full_name: str
    title: str | None
    institution: str | None
    department: str | None
    research_summary: str | None
    active_topics: str | None
    role_category: str | None
    duplicate_reasons: list[str]


@dataclass(frozen=True)
class CandidateScreeningResult:
    status: str
    score: float
    reasons: list[str]
    exclusions: list[str]
    warnings: list[str]


def normalize_text(value: str | None) -> str:
    return " ".join((value or "").lower().split())


def searchable_text(context: ScreeningContext) -> str:
    return normalize_text(
        " ".join(
            item
            for item in [
                context.full_name,
                context.title,
                context.research_summary,
                context.active_topics,
                context.role_category,
            ]
            if item
        ),
    )


def raw_context_text(context: ScreeningContext) -> str:
    return " ".join(
        item
        for item in [
            context.full_name,
            context.title,
            context.research_summary,
            context.active_topics,
            context.role_category,
        ]
        if item
    )


def contains_any(text: str, terms: set[str] | tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def career_stage_score(text: str, role_category: str | None) -> tuple[int, str]:
    if role_category == "assistant_professor" or "assistant professor" in text:
        return 18, "Assistant professor: strong accessibility signal."
    if role_category == "associate_professor" or "associate professor" in text:
        return 15, "Associate professor: good accessibility signal."
    if role_category in {"postdoc", "research_scientist", "research_professor", "fellow"}:
        return 16, "Research faculty/postdoc role: good accessibility signal."
    if "professor" in text and contains_any(text, COMPUTATIONAL_TERMS):
        return 10, "Full professor retained because the profile has computational/theory signals."
    if "professor" in text:
        return 5, "Full professor without a clear accessibility signal."
    return 6, "Career stage needs manual review."


def research_match_score(text: str) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    for _area, terms, reason in ARNAV_RESEARCH_AREAS:
        matched = sorted(term for term in terms if term in text)
        if matched:
            score += min(10, 4 + len(matched) * 2)
            reasons.append(f"{reason} Evidence terms: {', '.join(matched[:5])}.")
    return min(score, 35), reasons


def remote_feasibility_score(text: str) -> tuple[int, str]:
    if contains_any(text, COMPUTATIONAL_TERMS):
        matched = sorted(term for term in COMPUTATIONAL_TERMS if term in text)
        return 20, f"Remote/computational feasibility is supported by: {', '.join(matched[:5])}."
    if "theory" in text or "theoretical" in text:
        return 16, "Theoretical work suggests remote feasibility."
    return 6, "No clear computational or remote-friendly signal found."


def mentoring_score(text: str) -> tuple[int, str]:
    matched = sorted(term for term in MENTORING_TERMS if term in text)
    if matched:
        return 8, f"Mentoring or group signal found: {', '.join(matched[:4])}."
    return 3, "No explicit student, group, or mentoring signal found."


def contribution_score(text: str) -> tuple[int, str]:
    contribution_terms = {
        "analysis",
        "computational",
        "data",
        "modeling",
        "monte carlo",
        "numerical",
        "optimization",
        "python",
        "simulation",
        "software",
        "statistical",
        "visualization",
    }
    matched = sorted(term for term in contribution_terms if term in text)
    if matched:
        return min(10, 4 + len(matched)), f"Contribution path matches: {', '.join(matched[:5])}."
    return 2, "Contribution path is not obvious from the visible profile text."


def recent_activity_score(text: str) -> tuple[int, str]:
    years = sorted({int(match) for match in re.findall(r"\b20(?:2[2-6]|1[9])\b", text)})
    if years:
        recent_years = ", ".join(map(str, years[-3:]))
        return 10, f"Recent activity signal appears in visible text: {recent_years}."
    return 5, "No recent year appears in the directory text; recent papers must verify activity."


def extract_group_terms(text: str) -> set[str]:
    return {" ".join(match.lower().split()) for match in GROUP_NAME_RE.findall(text)}


def contacted_candidates(session: Session) -> list[Candidate]:
    return list(
        session.scalars(
            select(Candidate).where(
                Candidate.deleted_at.is_(None),
                Candidate.status.in_(CONTACTED_STATUSES),
            ),
        ),
    )


def same_group_warnings(session: Session, context: ScreeningContext) -> list[str]:
    text = raw_context_text(context)
    incoming_groups = extract_group_terms(text)
    if not incoming_groups:
        return []
    warnings: list[str] = []
    institution = normalize_text(context.institution)
    department = normalize_text(context.department)
    for candidate in contacted_candidates(session):
        if institution and normalize_text(candidate.institution) != institution:
            continue
        if (
            department
            and candidate.department
            and normalize_text(candidate.department) != department
        ):
            continue
        candidate_text = " ".join(
            item for item in [candidate.research_area, candidate.notes] if item
        )
        overlap = incoming_groups & extract_group_terms(candidate_text)
        for group in sorted(overlap):
            warnings.append(
                f"Same group/laboratory warning: {group} overlaps with contacted candidate "
                f"{candidate.full_name}.",
            )
    return warnings


def screen_candidate(session: Session, context: ScreeningContext) -> CandidateScreeningResult:
    text = searchable_text(context)
    reasons: list[str] = []
    exclusions: list[str] = []
    warnings: list[str] = []

    if contains_any(text, INACTIVE_TERMS):
        exclusions.append(
            "Excluded by default: emeritus, retired, inactive, or in-memoriam status.",
        )

    for duplicate_reason in context.duplicate_reasons:
        exclusions.append(
            f"Excluded by default: already present in local contact data ({duplicate_reason}).",
        )

    if contains_any(text, EXPERIMENTAL_TERMS) and not contains_any(text, COMPUTATIONAL_TERMS):
        warnings.append(
            "Experimental/hardware-heavy profile without a clear computational or "
            "theoretical path.",
        )

    warnings.extend(same_group_warnings(session, context))

    match_points, match_reasons = research_match_score(text)
    reasons.extend(match_reasons or ["Research match is weak from visible directory text."])
    remote_points, remote_reason = remote_feasibility_score(text)
    career_points, career_reason = career_stage_score(text, context.role_category)
    recent_points, recent_reason = recent_activity_score(text)
    mentoring_points, mentoring_reason = mentoring_score(text)
    contribution_points, contribution_reason = contribution_score(text)
    reasons.extend(
        [
            remote_reason,
            career_reason,
            recent_reason,
            mentoring_reason,
            contribution_reason,
        ],
    )

    score = float(
        match_points
        + remote_points
        + career_points
        + recent_points
        + mentoring_points
        + contribution_points
    )
    if exclusions:
        status = "EXCLUDED"
    elif warnings:
        status = "WARN"
    else:
        status = "INCLUDED"
    return CandidateScreeningResult(
        status=status,
        score=min(score, 100.0),
        reasons=reasons,
        exclusions=exclusions,
        warnings=warnings,
    )
