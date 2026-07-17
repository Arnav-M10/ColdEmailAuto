import html
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.candidate import Candidate
from app.models.discovery import (
    DepartmentImport,
    DepartmentImportStatus,
    DiscoveryCandidate,
    DiscoveryDecision,
)
from app.services.candidates import (
    add_email_address,
    create_candidate,
    detect_duplicate_warnings,
)
from app.services.web_safety import FetchResult

EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
WHITESPACE_RE = re.compile(r"\s+")
NAME_RE = re.compile(
    r"\b(?:Dr\.?\s+|Professor\s+|Prof\.?\s+)?([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){1,3})\b",
)

ROLE_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("assistant_professor", "Assistant Professor", ("assistant professor",)),
    ("associate_professor", "Associate Professor", ("associate professor",)),
    ("postdoc", "Postdoctoral Researcher", ("postdoc", "postdoctoral")),
    ("research_scientist", "Research Scientist", ("research scientist", "scientist")),
    ("research_professor", "Research Professor", ("research professor",)),
)

RESEARCH_TERMS = {
    "astrophysics",
    "cosmology",
    "plasma",
    "relativity",
    "computation",
    "computational",
    "simulation",
    "numerical",
    "data",
    "machine learning",
    "topology",
    "dynamical",
    "optimization",
    "uncertainty",
    "matrix",
}

REMOTE_TERMS = {"computational", "simulation", "numerical", "data", "software", "modeling"}
MENTORING_TERMS = {"students", "undergraduate", "mentor", "group", "lab", "opportunities"}
NON_NAME_TRAILING_WORDS = {"lab", "page", "homepage", "research", "email"} | RESEARCH_TERMS


@dataclass(frozen=True)
class ParsedBlock:
    text: str
    links: list[str]


@dataclass(frozen=True)
class DiscoveryPreview:
    full_name: str
    title: str | None
    role_category: str | None
    research_summary: str | None
    active_topics: str | None
    remote_feasibility: str | None
    mentoring_likelihood: str | None
    research_overlap: str | None
    confidence: float
    score: float
    official_email: str | None
    official_homepage: str | None
    source_url: str
    evidence: list[str]
    warnings: list[str]


class BlockHTMLParser(HTMLParser):
    block_tags = {"article", "section", "li", "tr", "div"}
    skip_tags = {"script", "style", "noscript"}

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.blocks: list[ParsedBlock] = []
        self._block_depth = 0
        self._text_parts: list[str] = []
        self._links: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.skip_tags:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in self.block_tags:
            if self._block_depth == 0:
                self._flush()
            self._block_depth += 1
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self._links.append(urljoin(self.base_url, href))

    def handle_endtag(self, tag: str) -> None:
        if tag in self.skip_tags and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag in self.block_tags and self._block_depth:
            self._block_depth -= 1
            if self._block_depth == 0:
                self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        cleaned = normalize_text(data)
        if cleaned:
            self._text_parts.append(cleaned)

    def _flush(self) -> None:
        text = normalize_text(" ".join(self._text_parts))
        if text:
            self.blocks.append(ParsedBlock(text=text, links=list(dict.fromkeys(self._links))))
        self._text_parts = []
        self._links = []

    def close(self) -> None:
        super().close()
        self._flush()


def normalize_text(value: str) -> str:
    return WHITESPACE_RE.sub(" ", html.unescape(value)).strip()


def role_for_text(text: str) -> tuple[str | None, str | None]:
    lowered = text.lower()
    for category, title, needles in ROLE_RULES:
        if any(needle in lowered for needle in needles):
            return category, title
    return None, None


def name_for_text(text: str) -> str | None:
    role_titles = "|".join(re.escape(rule[1]) for rule in ROLE_RULES)
    after_role = re.search(
        rf"(?:{role_titles})\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){{1,2}})",
        text,
    )
    if after_role:
        return clean_person_name(after_role.group(1))
    before_role = re.search(
        rf"([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){{1,2}})"
        rf"\s*(?:,|-|–)?\s+(?:{role_titles})",
        text,
    )
    if before_role:
        return clean_person_name(before_role.group(1))
    for match in NAME_RE.finditer(text):
        candidate = match.group(1).strip()
        lowered = candidate.lower()
        if any(word in lowered for word in {"assistant", "associate", "research", "professor"}):
            continue
        return clean_person_name(candidate)
    return None


def clean_person_name(value: str) -> str:
    parts = value.strip().split()
    if parts and parts[0].rstrip(".") in {"Dr", "Prof", "Professor"}:
        parts = parts[1:]
    while len(parts) > 2 and parts[-1].lower() in NON_NAME_TRAILING_WORDS:
        parts.pop()
    return " ".join(parts)


def topics_for_text(text: str) -> list[str]:
    lowered = text.lower()
    return sorted(term for term in RESEARCH_TERMS if term in lowered)


def score_preview(text: str, role_category: str | None) -> tuple[float, list[str], str, str, str]:
    lowered = text.lower()
    topics = topics_for_text(text)
    research_fit = min(30, len(topics) * 6)
    remote_fit = 20 if any(term in lowered for term in REMOTE_TERMS) else 6
    career_access = 15 if role_category in {"assistant_professor", "postdoc"} else 10
    activity = 10 if re.search(r"\b20(2[2-6]|1[9])\b", text) else 7
    mentoring = 10 if any(term in lowered for term in MENTORING_TERMS) else 4
    environment = 8
    score = float(research_fit + remote_fit + career_access + activity + mentoring + environment)
    warnings: list[str] = []
    if not topics:
        warnings.append("No clear overlap term found in visible page text.")
    remote = "High" if remote_fit == 20 else "Unclear"
    mentoring_text = "Mentioned on page" if mentoring == 10 else "No explicit mentoring signal"
    overlap = ", ".join(topics[:4]) if topics else "Needs manual review"
    return score, warnings, remote, mentoring_text, overlap


def extract_department_candidates(
    html_text: str,
    *,
    source_url: str,
    institution: str | None = None,
    department: str | None = None,
) -> list[DiscoveryPreview]:
    parser = BlockHTMLParser(source_url)
    parser.feed(html_text)
    parser.close()
    previews: list[DiscoveryPreview] = []
    seen_names: set[str] = set()
    for block in parser.blocks:
        role_category, title = role_for_text(block.text)
        if not role_category:
            continue
        full_name = name_for_text(block.text)
        if not full_name:
            continue
        normalized_name = full_name.lower()
        if normalized_name in seen_names:
            continue
        seen_names.add(normalized_name)
        email_match = EMAIL_RE.search(block.text)
        homepage = next((link for link in block.links if "mailto:" not in link), None)
        topics = topics_for_text(block.text)
        score, warnings, remote, mentoring, overlap = score_preview(block.text, role_category)
        confidence = 0.55
        if email_match:
            confidence += 0.15
        if homepage:
            confidence += 0.15
        if topics:
            confidence += 0.1
        previews.append(
            DiscoveryPreview(
                full_name=full_name,
                title=title,
                role_category=role_category,
                research_summary=block.text[:500],
                active_topics=", ".join(topics) or None,
                remote_feasibility=remote,
                mentoring_likelihood=mentoring,
                research_overlap=overlap,
                confidence=min(confidence, 0.95),
                score=score,
                official_email=email_match.group(0).lower() if email_match else None,
                official_homepage=homepage,
                source_url=source_url,
                evidence=[block.text[:700]],
                warnings=warnings,
            ),
        )
    return previews


def create_department_import(
    session: Session,
    *,
    source_url: str,
    fetch_result: FetchResult,
    previews: list[DiscoveryPreview],
    institution: str | None = None,
    department: str | None = None,
) -> DepartmentImport:
    department_import = DepartmentImport(
        source_url=source_url,
        final_url=fetch_result.final_url,
        source_title=None,
        status=DepartmentImportStatus.REVIEW_READY
        if previews
        else DepartmentImportStatus.EXTRACTION_FAILED,
        robots_allowed=fetch_result.robots_allowed,
        page_sha256=fetch_result.sha256,
        error_message=None if previews else "No eligible researchers found.",
    )
    session.add(department_import)
    session.flush()
    for preview in previews:
        warnings = list(preview.warnings)
        duplicate_warnings = detect_duplicate_warnings(
            session,
            full_name=preview.full_name,
            institution=institution,
            email=preview.official_email,
        )
        warnings.extend(f"Possible duplicate: {warning.reason}" for warning in duplicate_warnings)
        session.add(
            DiscoveryCandidate(
                import_id=department_import.id,
                full_name=preview.full_name,
                title=preview.title,
                institution=institution,
                department=department,
                role_category=preview.role_category,
                research_summary=preview.research_summary,
                active_topics=preview.active_topics,
                remote_feasibility=preview.remote_feasibility,
                mentoring_likelihood=preview.mentoring_likelihood,
                research_overlap=preview.research_overlap,
                confidence=preview.confidence,
                score=preview.score,
                official_email=preview.official_email,
                official_homepage=preview.official_homepage,
                source_url=preview.source_url,
                evidence_json=json.dumps(preview.evidence),
                warnings_json=json.dumps(warnings),
                decision=DiscoveryDecision.REVIEW_PENDING,
            ),
        )
    return department_import


def list_department_imports(session: Session) -> list[DepartmentImport]:
    return list(
        session.scalars(
            select(DepartmentImport).order_by(DepartmentImport.created_at.desc()),
        ),
    )


def get_department_import(session: Session, import_id: int) -> DepartmentImport | None:
    return session.get(DepartmentImport, import_id)


def list_discovery_candidates(session: Session, import_id: int) -> list[DiscoveryCandidate]:
    return list(
        session.scalars(
            select(DiscoveryCandidate)
            .where(DiscoveryCandidate.import_id == import_id)
            .order_by(DiscoveryCandidate.score.desc()),
        ),
    )


def get_discovery_candidate(session: Session, preview_id: int) -> DiscoveryCandidate | None:
    return session.get(DiscoveryCandidate, preview_id)


def reject_discovery_candidate(session: Session, preview: DiscoveryCandidate) -> None:
    preview.decision = DiscoveryDecision.REJECTED


def save_discovery_candidate(session: Session, preview: DiscoveryCandidate) -> Candidate:
    if preview.decision == DiscoveryDecision.SAVED and preview.saved_candidate_id:
        existing = session.get(Candidate, preview.saved_candidate_id)
        if existing is not None:
            return existing
    duplicate_warnings = detect_duplicate_warnings(
        session,
        full_name=preview.full_name,
        institution=preview.institution,
        email=preview.official_email,
    )
    if duplicate_warnings:
        raise ValueError("Resolve duplicate warnings before saving this candidate.")
    candidate = create_candidate(
        session,
        full_name=preview.full_name,
        title=preview.title,
        institution=preview.institution,
        department=preview.department,
        research_area=preview.research_overlap,
        official_profile_url=preview.official_homepage,
        notes=f"Imported from reviewed department page: {preview.source_url}",
    )
    if preview.official_email:
        add_email_address(
            session,
            candidate_id=candidate.id,
            email=preview.official_email,
            source_url=preview.source_url,
            source_type="official_department_page",
            confidence="HIGH" if preview.confidence >= 0.8 else "MEDIUM",
            verification_status="VERIFIED",
        )
    preview.decision = DiscoveryDecision.SAVED
    preview.saved_candidate_id = candidate.id
    return candidate
