import re
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.candidate import Candidate
from app.models.email_address import EmailAddress
from app.services.candidates import add_email_address
from app.services.drafting import primary_verified_email
from app.services.web_safety import SafeFetcher, SafeFetchError

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)


def ensure_verified_official_email(
    session: Session,
    *,
    candidate: Candidate,
) -> EmailAddress | None:
    existing = primary_verified_email(session, candidate.id)
    if existing is not None:
        return existing
    if not candidate.official_profile_url:
        return None
    try:
        result = SafeFetcher().fetch(candidate.official_profile_url, expected="html")
    except SafeFetchError:
        return None
    html = result.body.decode("utf-8", errors="replace")
    for email in EMAIL_RE.findall(html):
        if likely_official_email(email, candidate):
            return add_email_address(
                session,
                candidate_id=candidate.id,
                email=email,
                source_url=result.final_url,
                source_type="official_faculty_profile",
                confidence="HIGH",
                verification_status="VERIFIED",
            )
    return None


def likely_official_email(email: str, candidate: Candidate) -> bool:
    lowered = email.lower()
    if lowered.endswith((".png", ".jpg", ".jpeg", ".gif")):
        return False
    institution = (candidate.institution or "").lower()
    source_domain_hint = (
        "mit" in institution
        or "university" in institution
        or "college" in institution
        or ".edu" in lowered
    )
    return source_domain_hint and not lowered.startswith(("example@", "test@"))


def email_verification_metadata(email: EmailAddress | None) -> dict[str, object]:
    if email is None:
        return {"status": "MISSING_OFFICIAL_EMAIL"}
    return {
        "status": "VERIFIED",
        "email": email.email,
        "source_url": email.source_url,
        "retrieval_date": (email.retrieved_at or datetime.now(UTC)).isoformat(),
        "confidence": email.confidence,
    }
