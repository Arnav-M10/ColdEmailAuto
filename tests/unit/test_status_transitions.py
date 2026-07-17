import pytest

from app.models.candidate import CandidateStatus
from app.services.status import can_transition, validate_transition


def test_status_transition_blocks_draft_without_paper_analysis() -> None:
    assert not can_transition(CandidateStatus.SHORTLISTED, CandidateStatus.DRAFT_READY)
    with pytest.raises(ValueError):
        validate_transition(CandidateStatus.SHORTLISTED, CandidateStatus.DRAFT_READY)


def test_status_transition_allows_analysis_to_draft_ready() -> None:
    validate_transition(CandidateStatus.PAPER_ANALYZED, CandidateStatus.DRAFT_READY)

