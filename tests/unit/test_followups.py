from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.db.session import create_engine_for_url, initialize_database
from app.models.candidate import CandidateStatus
from app.models.draft import Draft
from app.services.candidates import create_candidate
from app.services.followups import (
    approved_drafts_for_candidate,
    mark_candidate_manually_sent_and_schedule_follow_up,
    suggested_follow_up_due_date,
)


def add_approved_draft(session: Session, candidate_id: int) -> Draft:
    draft = Draft(
        candidate_id=candidate_id,
        subject="Research inquiry",
        body_text="Short approved local draft.",
        body_html=None,
        word_count=90,
        generation_version="test",
        approved_by_user=True,
    )
    session.add(draft)
    session.flush()
    return draft


def test_follow_up_calculation_skips_weekends() -> None:
    assert suggested_follow_up_due_date(date(2026, 7, 17), business_days=8) == date(
        2026,
        7,
        29,
    )


def test_follow_up_requires_approved_draft(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'test.db'}")
    initialize_database(engine)

    with Session(engine) as session:
        candidate = create_candidate(
            session,
            full_name="Professor Jane Doe",
            title=None,
            institution=None,
            department=None,
            research_area=None,
            official_profile_url=None,
            notes=None,
        )
        candidate.status = CandidateStatus.DRAFT_READY

        with pytest.raises(ValueError, match="approved draft"):
            mark_candidate_manually_sent_and_schedule_follow_up(
                session,
                candidate=candidate,
                sent_on=date(2026, 7, 17),
            )


def test_follow_up_blocks_declines_and_second_follow_up(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'test.db'}")
    initialize_database(engine)

    with Session(engine) as session:
        candidate = create_candidate(
            session,
            full_name="Professor Jane Doe",
            title=None,
            institution=None,
            department=None,
            research_area=None,
            official_profile_url=None,
            notes=None,
        )
        candidate.status = CandidateStatus.DRAFT_READY
        add_approved_draft(session, candidate.id)

        task = mark_candidate_manually_sent_and_schedule_follow_up(
            session,
            candidate=candidate,
            sent_on=date(2026, 7, 17),
        )

        assert task.due_at.date() == date(2026, 7, 29)
        assert candidate.status == CandidateStatus.SENT
        assert approved_drafts_for_candidate(session, candidate.id)
        with pytest.raises(ValueError, match="Only one follow-up"):
            mark_candidate_manually_sent_and_schedule_follow_up(
                session,
                candidate=candidate,
                sent_on=date(2026, 7, 17),
            )

        candidate.status = CandidateStatus.DECLINED
        with pytest.raises(ValueError, match="declined"):
            mark_candidate_manually_sent_and_schedule_follow_up(
                session,
                candidate=candidate,
                sent_on=date(2026, 7, 17),
            )
