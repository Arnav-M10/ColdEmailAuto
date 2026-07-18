from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.candidate import Candidate, CandidateStatus
from app.models.draft import Draft
from app.models.email_address import EmailAddress
from app.models.outreach import OutreachEventType
from app.models.paper import EvidenceItem, PaperAnalysis
from app.services.assets import required_attachments_ready
from app.services.candidates import record_event

FORBIDDEN_PHRASES = {
    "robust",
    "leverage",
    "groundbreaking",
    "compelling",
    "fascinating",
    "utilize",
    "endeavor",
    "delve",
    "pivotal",
    "transformative",
    "very interesting",
    "cutting-edge",
    "remarkable",
    "sophisticated",
    "extensive",
    "comprehensive",
}
MIN_REVIEW_WORDS = 105
MAX_REVIEW_WORDS = 145


def word_count(text: str) -> int:
    body = text.split("Sincerely,", maxsplit=1)[0]
    return len([word for word in body.replace("\n", " ").split(" ") if word.strip()])


def body_paragraph_count(text: str) -> int:
    body = text.split("Sincerely,", maxsplit=1)[0].strip()
    paragraphs = [paragraph for paragraph in body.split("\n\n") if paragraph.strip()]
    if paragraphs and paragraphs[0].lower().startswith("dear "):
        paragraphs = paragraphs[1:]
    return len(paragraphs)


def contains_forbidden_phrase(text: str) -> list[str]:
    lowered = text.lower()
    return sorted(phrase for phrase in FORBIDDEN_PHRASES if phrase in lowered)


def primary_verified_email(session: Session, candidate_id: int) -> EmailAddress | None:
    return session.scalars(
        select(EmailAddress)
        .where(
            EmailAddress.candidate_id == candidate_id,
            EmailAddress.verification_status == "VERIFIED",
        )
        .order_by(EmailAddress.created_at.desc()),
    ).first()


def generate_manual_draft(
    session: Session,
    *,
    candidate: Candidate,
    analysis: PaperAnalysis,
    evidence: EvidenceItem,
) -> Draft:
    last_name = candidate.full_name.strip().split()[-1]
    evidence_excerpt = evidence.evidence_text[:150].strip().rstrip(".")
    body = (
        f"Dear Professor {last_name},\n\n"
        "I am an incoming student at the Texas Academy of Mathematics and Science at the "
        "University of North Texas. "
        f"I enjoyed reading your paper {analysis.title}. "
        f"I was mainly intrigued by {evidence.claim}. "
        f"The part I noted from the paper was: {evidence_excerpt}.\n\n"
        f"My recent work includes {analysis.connection_to_arnav}. "
        "I am especially interested in careful computational work where small checks can "
        "make the physics or mathematics clearer. "
        "I would be glad to help with a suitable project through coding, "
        "data analysis, numerical checks, or visualization. "
        "I have attached my resume and research portfolio for context.\n\n"
        "Sincerely,\n"
        "Arnav Mittal\n"
        "Incoming Student, TAMS\n"
        "University of North Texas\n"
        "ArnavMittal@my.unt.edu"
    )
    draft = Draft(
        candidate_id=candidate.id,
        subject=f"Research inquiry - {analysis.title[:60]}",
        body_text=body,
        body_html=None,
        word_count=word_count(body),
        generation_version="manual-analysis-v1",
        approved_by_user=False,
    )
    session.add(draft)
    candidate.status = CandidateStatus.DRAFT_READY
    record_event(
        session,
        candidate_id=candidate.id,
        event_type=OutreachEventType.DRAFT_CREATED,
        notes=f"Draft generated from analysis {analysis.id}.",
    )
    return draft


def validate_draft_approval(
    session: Session,
    *,
    draft: Draft,
    project_root_override: Path | None = None,
) -> list[str]:
    errors: list[str] = []
    if primary_verified_email(session, draft.candidate_id) is None:
        errors.append("A verified official email is required.")
    if contains_forbidden_phrase(draft.body_text):
        errors.append("Draft contains forbidden wording.")
    if draft.word_count < MIN_REVIEW_WORDS or draft.word_count > MAX_REVIEW_WORDS:
        errors.append("Draft must be 105-145 words excluding the signoff.")
    if body_paragraph_count(draft.body_text) != 2:
        errors.append("Draft must use exactly two concise body paragraphs.")
    unsupported = unsupported_factual_sentences(session, draft=draft)
    if unsupported:
        errors.append("Draft contains unsupported factual sentence(s).")
    if not required_attachments_ready(project_root_override):
        errors.append("Required resume and portfolio PDFs must be valid.")
    return errors


def sentence_claim_checks(session: Session, *, draft: Draft) -> list[dict[str, str]]:
    analyses = list(
        session.scalars(
            select(PaperAnalysis)
            .where(PaperAnalysis.candidate_id == draft.candidate_id)
            .order_by(PaperAnalysis.created_at.desc()),
        ),
    )
    evidence_items: list[EvidenceItem] = []
    for analysis in analyses:
        evidence_items.extend(
            session.scalars(select(EvidenceItem).where(EvidenceItem.analysis_id == analysis.id)),
        )
    evidence_text = " ".join(
        [
            *[analysis.title for analysis in analyses],
            *[analysis.connection_to_arnav for analysis in analyses],
            *[item.claim for item in evidence_items],
            *[item.evidence_text for item in evidence_items],
        ],
    ).lower()
    checks: list[dict[str, str]] = []
    for sentence in split_sentences(draft.body_text):
        lowered = sentence.lower()
        if lowered.startswith(("dear ", "sincerely", "arnav mittal", "incoming student")):
            classification = "PERSONAL_BACKGROUND"
            reason = "Signoff or salutation."
        elif (
            "incoming student" in lowered
            or "my recent work includes" in lowered
            or "i am especially interested" in lowered
            or "university of north texas" in lowered
        ):
            classification = "PERSONAL_BACKGROUND"
            reason = "Matches allowed personal background."
        elif "i would be glad" in lowered or "attached my resume" in lowered:
            classification = "GENERAL_REQUEST"
            reason = "General request or attachment reminder."
        elif any(fragment in evidence_text for fragment in key_fragments(lowered)):
            classification = "SUPPORTED"
            reason = "Grounded in saved analysis or explicit evidence."
        else:
            classification = "UNSUPPORTED"
            reason = "No matching saved evidence was found."
        checks.append({"sentence": sentence, "classification": classification, "reason": reason})
    return checks


def unsupported_factual_sentences(session: Session, *, draft: Draft) -> list[dict[str, str]]:
    return [
        check
        for check in sentence_claim_checks(session, draft=draft)
        if check["classification"] == "UNSUPPORTED"
    ]


def split_sentences(text: str) -> list[str]:
    text = text.split("Sincerely,", maxsplit=1)[0]
    normalized = text.replace("\n", " ")
    sentences: list[str] = []
    current = ""
    for character in normalized:
        current += character
        if character in ".!?":
            sentence = current.strip()
            if sentence:
                sentences.append(sentence)
            current = ""
    if current.strip():
        sentences.append(current.strip())
    return sentences


def key_fragments(sentence: str) -> list[str]:
    words = [word.strip(".,:;()").lower() for word in sentence.split()]
    meaningful = [word for word in words if len(word) > 5]
    fragments = []
    for start in range(max(len(meaningful) - 2, 0)):
        fragments.append(" ".join(meaningful[start : start + 3]))
    fragments.extend(meaningful)
    return fragments


def approve_draft(session: Session, draft: Draft) -> None:
    errors = validate_draft_approval(session, draft=draft)
    if errors:
        raise ValueError("; ".join(errors))
    draft.approved_by_user = True
    draft.approved_at = datetime.now(UTC)
    record_event(
        session,
        candidate_id=draft.candidate_id,
        event_type=OutreachEventType.DRAFT_APPROVED,
        notes="Draft approved locally. Outlook integration is not implemented.",
    )


def list_drafts(session: Session) -> list[Draft]:
    return list(session.scalars(select(Draft).order_by(Draft.created_at.desc())))


def get_draft(session: Session, draft_id: int) -> Draft | None:
    return session.get(Draft, draft_id)
