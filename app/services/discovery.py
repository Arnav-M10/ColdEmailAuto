import html
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

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
PERSON_NAME_PART_RE = r"(?:[A-Z]\.|[A-Z][^\W\d_]+(?:[.'’-][^\W\d_]+)*)"
NAME_RE = re.compile(
    rf"\b(?:Dr\.?\s+|Professor\s+|Prof\.?\s+)?"
    rf"({PERSON_NAME_PART_RE}(?:\s+{PERSON_NAME_PART_RE}){{1,3}})\b",
)
COMMA_NAME_RE = re.compile(
    rf"\b({PERSON_NAME_PART_RE}),\s+({PERSON_NAME_PART_RE}(?:\s+{PERSON_NAME_PART_RE}){{0,2}})\b",
)

ROLE_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("assistant_professor", "Assistant Professor", ("assistant professor",)),
    ("associate_professor", "Associate Professor", ("associate professor",)),
    ("professor", "Professor", ("professor",)),
    ("lecturer", "Lecturer", ("lecturer",)),
    ("postdoc", "Postdoctoral Researcher", ("postdoc", "postdoctoral")),
    ("fellow", "Fellow", ("pappalardo fellow", "research fellow", "fellow in physics")),
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
REJECT_PERSON_PHRASES = {
    "graduate program",
    "undergraduate program",
    "research areas",
    "admissions",
    "news",
    "events",
    "about",
    "resources",
    "student resources",
    "academic programs",
    "latest physics news",
    "recent news",
    "footer menu",
    "spotlight on",
}
NON_PERSON_TOKENS = {
    "about",
    "admissions",
    "areas",
    "calendar",
    "contact",
    "directory",
    "events",
    "faculty",
    "fellowship",
    "fellowships",
    "graduate",
    "login",
    "menu",
    "news",
    "physics",
    "program",
    "programs",
    "research",
    "resources",
    "students",
    "undergraduate",
}
SKIP_CONTEXT_TOKENS = {
    "archive",
    "banner",
    "breadcrumb",
    "event",
    "filter",
    "footer",
    "header",
    "hero",
    "menu",
    "nav",
    "navigation",
    "news",
    "post",
    "search",
}
PERSON_CONTEXT_TOKENS = {
    "card",
    "directory",
    "faculty",
    "listing",
    "member",
    "people",
    "person",
    "profile",
    "researcher",
    "staff",
}
DIRECTORY_LINK_REJECT_PHRASES = {
    "graduate admissions",
    "graduate program",
    "undergraduate program",
    "mentoring programs",
    "research areas",
    "student resources",
    "latest physics news",
    "news",
    "events",
    "calendar",
    "contact",
    "login",
}


@dataclass(frozen=True)
class ParsedBlock:
    text: str
    links: list[str]
    link_texts: list[str]
    source_element: str
    title_hint: str | None = None
    is_structured_person: bool = False


@dataclass(frozen=True)
class ParsedLink:
    text: str
    url: str
    source_element: str


@dataclass(frozen=True)
class DirectorySuggestion:
    source_url: str
    directory_url: str
    reason: str
    confidence: float


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
    source_element: str
    evidence: list[str]
    warnings: list[str]


@dataclass
class HtmlNode:
    tag: str
    attrs: dict[str, str]
    parent: "HtmlNode | None" = None
    children: list["HtmlNode"] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)

    @property
    def attr_text(self) -> str:
        return " ".join(
            value for key, value in self.attrs.items() if key in {"class", "id", "role"}
        ).lower()

    def text_content(self) -> str:
        parts: list[str] = []
        if self.text_parts:
            parts.extend(self.text_parts)
        for child in self.children or []:
            child_text = child.text_content()
            if child_text:
                parts.append(child_text)
        return normalize_text(" ".join(parts))

    def css_hint(self) -> str:
        hints: list[str] = []
        if self.attrs.get("id"):
            hints.append(f"#{self.attrs['id']}")
        if self.attrs.get("class"):
            classes = ".".join(self.attrs["class"].split()[:3])
            if classes:
                hints.append(f".{classes}")
        return "".join(hints)

    def source_label(self) -> str:
        text = self.text_content()
        if len(text) > 900:
            text = f"{text[:900]}..."
        return f"<{self.tag}{self.css_hint()}> {text}"

    def ancestors(self) -> list["HtmlNode"]:
        nodes: list[HtmlNode] = []
        current = self.parent
        while current is not None:
            nodes.append(current)
            current = current.parent
        return nodes


class DiscoveryHTMLParser(HTMLParser):
    skip_tags = {"script", "style", "noscript"}
    void_tags = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.root = HtmlNode("document", {})
        self._stack: list[HtmlNode] = [self.root]
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.skip_tags:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        attr_map = {key.lower(): value or "" for key, value in attrs}
        node = HtmlNode(tag.lower(), attr_map, parent=self._stack[-1])
        self._stack[-1].children.append(node)
        if node.tag in self.void_tags:
            return
        self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.skip_tags and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        tag = tag.lower()
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        cleaned = normalize_text(data)
        if cleaned:
            self._stack[-1].text_parts.append(cleaned)

    def iter_nodes(self) -> list[HtmlNode]:
        nodes: list[HtmlNode] = []

        def visit(node: HtmlNode) -> None:
            nodes.append(node)
            for child in node.children:
                visit(child)

        visit(self.root)
        return nodes

    def links(self) -> list[ParsedLink]:
        links: list[ParsedLink] = []
        for node in self.iter_nodes():
            if node.tag != "a":
                continue
            href = node.attrs.get("href")
            text = node.text_content()
            if href and text:
                links.append(
                    ParsedLink(
                        text=text,
                        url=urljoin(self.base_url, href),
                        source_element=node.source_label(),
                    ),
                )
        return links

    def candidate_blocks(self) -> list[ParsedBlock]:
        blocks: list[ParsedBlock] = []
        seen: set[str] = set()
        for node in self.iter_nodes():
            if should_skip_node(node):
                continue
            text = node.text_content()
            if not text or len(text) < 8:
                continue
            if node.tag in {"article", "li", "tr"} or is_structured_person_node(node):
                block = parsed_block_from_node(node, self.base_url)
                key = block.source_element
                if key not in seen:
                    seen.add(key)
                    blocks.append(block)
            if node.tag in {"h2", "h3", "h4"} and likely_human_name(text):
                heading_candidate = heading_block(node, self.base_url)
                if heading_candidate:
                    key = heading_candidate.source_element
                    if key not in seen:
                        seen.add(key)
                        blocks.append(heading_candidate)
        return blocks


def normalize_text(value: str) -> str:
    return WHITESPACE_RE.sub(" ", html.unescape(value)).strip()


def compact_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def phrase_rejected(value: str) -> bool:
    lowered = compact_key(value)
    return any(phrase in lowered for phrase in REJECT_PERSON_PHRASES)


def should_skip_node(node: HtmlNode) -> bool:
    if node.tag in {"nav", "header", "footer", "form", "button", "select", "option"}:
        return True
    if any(token in node.attr_text for token in SKIP_CONTEXT_TOKENS):
        return True
    ancestor_skip_tokens = {"banner", "breadcrumb", "footer", "header", "menu", "nav", "navigation"}
    for current in [node, *node.ancestors()]:
        if current.tag in {"nav", "header", "footer", "form"}:
            return True
    for current in node.ancestors():
        if any(token in current.attr_text for token in ancestor_skip_tokens):
            return True
    return False


def is_structured_person_node(node: HtmlNode) -> bool:
    class_values = node.attrs.get("class", "").lower().split()
    id_value = node.attrs.get("id", "").lower()
    class_or_id = " ".join([*class_values, id_value])
    container_classes = {
        "directory-card",
        "faculty-card",
        "member-card",
        "people-card",
        "person-card",
        "profile-card",
        "researcher-card",
        "staff-card",
    }
    if any(value in container_classes for value in class_values):
        return True
    if any(token in class_or_id for token in ("person-listing", "profile-listing")):
        return True
    if node.tag in {"article", "li", "tr"} and any(
        token in class_or_id for token in PERSON_CONTEXT_TOKENS
    ):
        return True
    if node.attrs.get("itemtype") and "person" in node.attrs["itemtype"].lower():
        return True
    if node.attrs.get("typeof") and "person" in node.attrs["typeof"].lower():
        return True
    return False


def node_links(node: HtmlNode, base_url: str) -> list[ParsedLink]:
    links: list[ParsedLink] = []

    def visit(current: HtmlNode) -> None:
        if current.tag == "a":
            href = current.attrs.get("href")
            text = current.text_content()
            if href and text:
                links.append(
                    ParsedLink(
                        text=text,
                        url=urljoin(base_url, href),
                        source_element=current.source_label(),
                    ),
                )
        for child in current.children or []:
            visit(child)

    visit(node)
    return links


def parsed_block_from_node(node: HtmlNode, base_url: str) -> ParsedBlock:
    links = node_links(node, base_url)
    return ParsedBlock(
        text=node.text_content(),
        links=[link.url for link in links],
        link_texts=[link.text for link in links],
        source_element=node.source_label(),
        title_hint=title_hint_from_node(node),
        is_structured_person=is_structured_person_node(node),
    )


def heading_block(node: HtmlNode, base_url: str) -> ParsedBlock | None:
    parent = node.parent
    if parent is None or parent.children is None:
        return parsed_block_from_node(node, base_url)
    try:
        start_index = parent.children.index(node)
    except ValueError:
        return parsed_block_from_node(node, base_url)
    parts = [node.text_content()]
    links = node_links(node, base_url)
    for sibling in parent.children[start_index + 1 : start_index + 5]:
        if sibling.tag in {"h1", "h2", "h3", "h4"}:
            break
        if should_skip_node(sibling):
            continue
        text = sibling.text_content()
        if text:
            parts.append(text)
        links.extend(node_links(sibling, base_url))
    text = normalize_text(" ".join(parts))
    if not text:
        return None
    source = f"{node.source_label()}"
    return ParsedBlock(
        text=text,
        links=list(dict.fromkeys(link.url for link in links)),
        link_texts=list(dict.fromkeys(link.text for link in links)),
        source_element=source,
        title_hint=None,
        is_structured_person=is_structured_person_node(node)
        or (parent is not None and is_structured_person_node(parent)),
    )


def title_hint_from_node(node: HtmlNode) -> str | None:
    hints: list[str] = []

    def visit(current: HtmlNode) -> None:
        context = current.attr_text
        if (
            ("job-title" in context or "title" in context or "position" in context)
            and not should_skip_node(current)
        ):
            text = current.text_content()
            if text:
                hints.append(text)
        for child in current.children:
            visit(child)

    visit(node)
    return clean_title(hints[0]) if hints else None


def likely_human_name(value: str) -> bool:
    name = clean_person_name(value)
    if not name or phrase_rejected(name):
        return False
    tokens = name.split()
    if not 2 <= len(tokens) <= 4:
        return False
    lowered_tokens = {token.rstrip(".,:;").lower() for token in tokens}
    if lowered_tokens & NON_PERSON_TOKENS:
        return False
    if any(token.isupper() and len(token) > 1 for token in tokens):
        return False
    return bool(re.fullmatch(rf"{PERSON_NAME_PART_RE}(?:\s+{PERSON_NAME_PART_RE}){{1,3}}", name))


def link_is_profile_like(url: str, text: str, name: str) -> bool:
    lowered_url = url.lower()
    lowered_text = text.lower()
    name_slug = "-".join(token.lower().strip(".") for token in name.split())
    if lowered_url.startswith("mailto:"):
        return False
    if likely_human_name(text):
        return True
    if name_slug and name_slug in lowered_url:
        return True
    profile_terms = ("profile", "people", "person", "faculty")
    return any(token in lowered_url or token in lowered_text for token in profile_terms)


def supporting_signals(block: ParsedBlock, name: str, role_category: str | None) -> set[str]:
    signals: set[str] = set()
    text = block.text
    if role_category:
        signals.add("academic title")
    if EMAIL_RE.search(text):
        signals.add("university email")
    if topics_for_text(text):
        signals.add("research role")
    if block.is_structured_person:
        signals.add("faculty-card structure")
    for index, link in enumerate(block.links):
        link_text = block.link_texts[index] if index < len(block.link_texts) else link
        if link_is_profile_like(link, link_text, name):
            signals.add("profile link")
            break
    return signals


def role_for_text(text: str) -> tuple[str | None, str | None]:
    lowered = text.lower()
    for category, title, needles in ROLE_RULES:
        if any(needle in lowered for needle in needles):
            return category, title
    return None, None


def name_for_text(text: str) -> str | None:
    role_titles = "|".join(re.escape(rule[1]) for rule in ROLE_RULES)
    after_role = re.search(
        rf"(?:{role_titles})\s+({PERSON_NAME_PART_RE}(?:\s+{PERSON_NAME_PART_RE}){{1,2}})",
        text,
    )
    if after_role and likely_human_name(after_role.group(1)):
        return clean_person_name(after_role.group(1))
    before_role = re.search(
        rf"({PERSON_NAME_PART_RE}(?:\s+{PERSON_NAME_PART_RE}){{1,2}})"
        rf"\s*(?:,|-|–)?\s+(?:{role_titles})",
        text,
    )
    if before_role and likely_human_name(before_role.group(1)):
        return clean_person_name(before_role.group(1))
    comma_name = COMMA_NAME_RE.search(text)
    if comma_name:
        converted = clean_person_name(f"{comma_name.group(2)} {comma_name.group(1)}")
        if likely_human_name(converted):
            return converted
    for match in NAME_RE.finditer(text):
        candidate = match.group(1).strip()
        lowered = candidate.lower()
        if any(word in lowered for word in {"assistant", "associate", "research", "professor"}):
            continue
        cleaned = clean_person_name(candidate)
        if likely_human_name(cleaned):
            return cleaned
    return None


def clean_person_name(value: str) -> str:
    parts = normalize_text(value).strip(".,:;|").split()
    if parts and parts[0].rstrip(".") in {"Dr", "Prof", "Professor"}:
        parts = parts[1:]
    while len(parts) > 2 and parts[-1].lower() in NON_NAME_TRAILING_WORDS:
        parts.pop()
    return " ".join(parts)


def topics_for_text(text: str) -> list[str]:
    lowered = text.lower()
    return sorted(term for term in RESEARCH_TERMS if term in lowered)


def name_from_block(block: ParsedBlock) -> str | None:
    for link_text in block.link_texts:
        if likely_human_name(link_text):
            return clean_person_name(link_text)
    return name_for_text(block.text)


def title_for_text(text: str, fallback: str | None) -> str | None:
    title_patterns = [
        r"(Assistant Professor[^.\n|,;]*)",
        r"(Associate Professor[^.\n|,;]*)",
        r"([A-Z][A-Za-z.&()' -]+ Professor[^.\n|,;]*)",
        r"(Professor[^.\n|,;]*)",
        r"(Postdoctoral Researcher[^.\n|,;]*)",
        r"(Pappalardo Fellow[^.\n|,;]*)",
        r"(Research Scientist[^.\n|,;]*)",
        r"(Lecturer[^.\n|,;]*)",
    ]
    for pattern in title_patterns:
        match = re.search(pattern, text)
        if match:
            return clean_title(normalize_text(match.group(1)))
    return fallback


def clean_title(value: str) -> str:
    stop_phrases = (
        " A pioneer ",
        " Best known ",
        " Explores ",
        " Focus ",
        " Focuses ",
        " Has pioneered ",
        " Investigates ",
        " My research ",
        " Research ",
        " Researches ",
        " Searches ",
        " Specialist ",
        " Studies ",
        " Uses ",
        " Utilizes ",
        " Works ",
    )
    cleaned = value
    for phrase in stop_phrases:
        index = cleaned.find(phrase)
        if index > 0:
            cleaned = cleaned[:index]
    return cleaned.strip(" ,;.-")


def parse_discovery_html(html_text: str, source_url: str) -> DiscoveryHTMLParser:
    parser = DiscoveryHTMLParser(source_url)
    parser.feed(html_text)
    parser.close()
    return parser


def directory_score(link: ParsedLink) -> tuple[int, str]:
    text = compact_key(link.text)
    path = compact_key(urlparse(link.url).path)
    combined = f"{text} {path}"
    if any(phrase in combined for phrase in DIRECTORY_LINK_REJECT_PHRASES):
        return 0, "Rejected non-directory navigation link."
    score = 0
    reasons: list[str] = []
    if "faculty directory" in combined:
        score += 90
        reasons.append("link says faculty directory")
    elif "faculty" in combined:
        score += 70
        reasons.append("link targets faculty")
    if "people directory" in combined:
        score += 75
        reasons.append("link says people directory")
    elif "people" in combined:
        score += 55
        reasons.append("link targets people")
    if "directory" in combined:
        score += 35
        reasons.append("link targets a directory")
    if "staff" in combined:
        score -= 20
    return score, "; ".join(reasons) or "No directory signal."


def page_looks_like_directory(html_text: str, source_url: str) -> bool:
    path = compact_key(urlparse(source_url).path)
    return any(token in path for token in ("faculty", "people", "directory"))


def suggest_directory_page(html_text: str, *, source_url: str) -> DirectorySuggestion:
    if page_looks_like_directory(html_text, source_url):
        return DirectorySuggestion(
            source_url=source_url,
            directory_url=source_url,
            reason="The submitted URL already looks like a faculty or people directory.",
            confidence=0.9,
        )
    parser = parse_discovery_html(html_text, source_url)
    suggestions: list[tuple[int, ParsedLink, str]] = []
    source_host = urlparse(source_url).netloc.lower()
    for link in parser.links():
        parsed = urlparse(link.url)
        if parsed.scheme not in {"http", "https"}:
            continue
        if parsed.netloc.lower() != source_host:
            continue
        score, reason = directory_score(link)
        if score:
            suggestions.append((score, link, reason))
    if not suggestions:
        return DirectorySuggestion(
            source_url=source_url,
            directory_url=source_url,
            reason="No stronger official faculty or people directory link was found.",
            confidence=0.35,
        )
    suggestions.sort(key=lambda item: item[0], reverse=True)
    best_score, best_link, reason = suggestions[0]
    return DirectorySuggestion(
        source_url=source_url,
        directory_url=best_link.url,
        reason=f"{reason}. Source element: {best_link.source_element}",
        confidence=min(best_score / 100, 0.95),
    )


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
    parser = parse_discovery_html(html_text, source_url)
    previews: list[DiscoveryPreview] = []
    seen_names: set[str] = set()
    for block in parser.candidate_blocks():
        if phrase_rejected(block.text):
            continue
        role_category, title = role_for_text(block.text)
        full_name = name_from_block(block)
        if not full_name:
            continue
        if not likely_human_name(full_name):
            continue
        signals = supporting_signals(block, full_name, role_category)
        if not signals:
            continue
        normalized_name = full_name.lower()
        if normalized_name in seen_names:
            continue
        seen_names.add(normalized_name)
        email_match = EMAIL_RE.search(block.text)
        homepage = next(
            (
                link
                for index, link in enumerate(block.links)
                if link_is_profile_like(
                    link,
                    block.link_texts[index] if index < len(block.link_texts) else link,
                    full_name,
                )
            ),
            None,
        )
        topics = topics_for_text(block.text)
        score, warnings, remote, mentoring, overlap = score_preview(block.text, role_category)
        if not role_category:
            warnings.append("No explicit academic title found; verify this is a researcher.")
        confidence = 0.45
        confidence += min(0.25, len(signals) * 0.08)
        if email_match:
            confidence += 0.15
        if homepage:
            confidence += 0.15
        if topics:
            confidence += 0.1
        title_text = block.text
        if title_text.startswith(full_name):
            title_text = title_text[len(full_name) :].strip()
        title = block.title_hint or title_for_text(title_text, title)
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
                source_element=block.source_element,
                evidence=[
                    f"Source URL: {source_url}",
                    f"Source element: {block.source_element}",
                    f"Supporting signals: {', '.join(sorted(signals))}",
                    f"Visible text: {block.text[:700]}",
                ],
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
