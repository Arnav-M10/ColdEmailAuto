from sqlalchemy.orm import Session

from app.db.session import create_engine_for_url, initialize_database
from app.services.candidates import (
    add_email_address,
    create_candidate,
    detect_duplicate_warnings,
    import_contacted_csv,
    preview_contacted_csv,
)


def test_duplicate_detection_matches_email_and_name_institution() -> None:
    engine = create_engine_for_url("sqlite:///:memory:")
    initialize_database(engine)

    with Session(engine) as session:
        candidate = create_candidate(
            session,
            full_name="Professor Jane Doe",
            title=None,
            institution="Example University",
            department=None,
            research_area=None,
            official_profile_url=None,
            notes=None,
        )
        add_email_address(
            session,
            candidate_id=candidate.id,
            email="JANE.DOE@EXAMPLE.EDU",
            source_url="https://example.edu/jane-doe",
            source_type="official_university_page",
            confidence="HIGH",
            verification_status="VERIFIED",
        )
        session.commit()

        warnings = detect_duplicate_warnings(
            session,
            full_name="Professor Jane Doe",
            institution="Example University",
            email="jane.doe@example.edu",
        )

    assert {warning.reason for warning in warnings} == {
        "Matching verified email",
        "Matching name and institution",
    }


def test_contacted_csv_preview_flags_invalid_email() -> None:
    rows = preview_contacted_csv("name,email,institution,status\nAda,not-an-email,Ex,SENT\n")

    assert len(rows) == 1
    assert not rows[0].valid
    assert rows[0].error == "Enter a valid official email address."


def test_contacted_csv_import_skips_duplicate() -> None:
    engine = create_engine_for_url("sqlite:///:memory:")
    initialize_database(engine)

    with Session(engine) as session:
        create_candidate(
            session,
            full_name="Ada",
            title=None,
            institution="Example",
            department=None,
            research_area=None,
            official_profile_url=None,
            notes=None,
        )
        session.commit()

        result = import_contacted_csv(
            session,
            "name,email,institution,status\nAda,a@example.edu,Example,SENT\n",
        )

    assert result.imported == 0
    assert result.skipped == 1
