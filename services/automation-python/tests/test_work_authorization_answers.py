"""Table-driven tests for the two work-authorization questions every portal asks.

A portal does not ask for a paragraph about your visa. It asks two yes/no
questions, usually as radio buttons:

    Are you legally authorized to work in the United States?
    Will you now or in the future require sponsorship for employment visa status?

They are separate questions with separate answers, and someone on OPT answers
Yes to both. A free-text summary can fill neither.
"""
from __future__ import annotations

from typing import Any

import pytest

from applyocalypse_automation.answers import propose_answer_for_detected_field


def profile_with(work_authorization: dict[str, Any]) -> dict[str, Any]:
    return {"profile": {"legalName": "Grace Hopper", "workAuthorization": work_authorization}}


CITIZEN = profile_with(
    {"status": "US_CITIZEN", "authorizedInUs": True, "sponsorshipNeed": "NEVER", "summary": "US citizen."}
)
OPT = profile_with(
    {"status": "F1_OPT", "authorizedInUs": True, "sponsorshipNeed": "FUTURE", "summary": "F-1 student on OPT."}
)
H1B = profile_with(
    {"status": "H1B", "authorizedInUs": True, "sponsorshipNeed": "NOW", "summary": "H-1B."}
)
UNAUTHORIZED = profile_with(
    {
        "status": "NOT_YET_AUTHORIZED",
        "authorizedInUs": False,
        "sponsorshipNeed": "NOW",
        "summary": "Not authorized yet.",
    }
)

AUTHORIZATION_LABELS = (
    "Are you legally authorized to work in the United States?",
    "Are you authorized to work in the US?",
    "Are you eligible to work in the United States?",
)

SPONSORSHIP_LABELS = (
    "Will you now or in the future require sponsorship for employment visa status?",
    "Do you require visa sponsorship?",
    "Will you require sponsorship?",
)


@pytest.mark.parametrize("label", AUTHORIZATION_LABELS)
@pytest.mark.parametrize(
    ("profile", "expected"),
    [(CITIZEN, "Yes"), (OPT, "Yes"), (H1B, "Yes"), (UNAUTHORIZED, "No")],
)
def test_authorization_question_gets_a_yes_or_no(label: str, profile: dict[str, Any], expected: str) -> None:
    answer = propose_answer_for_detected_field(
        field_label=label, field_type="radio", canonical_profile=profile
    )
    assert answer.proposed_value == expected
    assert answer.source == "PROFILE"


@pytest.mark.parametrize("label", SPONSORSHIP_LABELS)
@pytest.mark.parametrize(
    ("profile", "expected"),
    [(CITIZEN, "No"), (OPT, "Yes"), (H1B, "Yes"), (UNAUTHORIZED, "Yes")],
)
def test_sponsorship_question_gets_a_yes_or_no(label: str, profile: dict[str, Any], expected: str) -> None:
    answer = propose_answer_for_detected_field(
        field_label=label, field_type="radio", canonical_profile=profile
    )
    assert answer.proposed_value == expected
    assert answer.source == "PROFILE"


def test_opt_says_yes_to_sponsorship_even_though_it_says_yes_to_authorization() -> None:
    """The knockout. Authorized today and needing sponsorship later are both true."""
    authorized = propose_answer_for_detected_field(
        field_label="Are you legally authorized to work in the United States?",
        field_type="radio",
        canonical_profile=OPT,
    )
    sponsorship = propose_answer_for_detected_field(
        field_label="Will you now or in the future require sponsorship for employment visa status?",
        field_type="radio",
        canonical_profile=OPT,
    )
    assert (authorized.proposed_value, sponsorship.proposed_value) == ("Yes", "Yes")


@pytest.mark.parametrize(
    ("profile", "expected"),
    [(CITIZEN, "Yes"), (OPT, "No"), (H1B, "No"), (UNAUTHORIZED, "No")],
)
def test_compound_question_is_answered_as_one_question(profile: dict[str, Any], expected: str) -> None:
    """"Authorized to work without sponsorship" is Yes only when both hold."""
    answer = propose_answer_for_detected_field(
        field_label="Are you legally authorized to work in the US without sponsorship?",
        field_type="radio",
        canonical_profile=profile,
    )
    assert answer.proposed_value == expected


@pytest.mark.parametrize("field_type", ["radio", "select", "boolean", "aria_radiogroup", "checkbox"])
def test_every_choice_widget_gets_the_yes_or_no(field_type: str) -> None:
    answer = propose_answer_for_detected_field(
        field_label="Are you legally authorized to work in the United States?",
        field_type=field_type,
        canonical_profile=CITIZEN,
    )
    assert answer.proposed_value == "Yes"


def test_work_authorization_always_requires_review() -> None:
    """A wrong answer here is a misrepresentation, so it is never auto-filled."""
    for profile in (CITIZEN, OPT, H1B, UNAUTHORIZED):
        for label in AUTHORIZATION_LABELS + SPONSORSHIP_LABELS:
            answer = propose_answer_for_detected_field(
                field_label=label,
                field_type="radio",
                canonical_profile=profile,
                autofill_approved_defaults=True,
            )
            assert answer.requires_review is True, f"{label} must stay review-gated"


def test_free_text_field_still_gets_the_summary() -> None:
    answer = propose_answer_for_detected_field(
        field_label="Describe your work authorization", field_type="textarea", canonical_profile=OPT
    )
    assert answer.proposed_value == "F-1 student on OPT."


def test_unanswered_profile_proposes_nothing() -> None:
    answer = propose_answer_for_detected_field(
        field_label="Are you legally authorized to work in the United States?",
        field_type="radio",
        canonical_profile=profile_with({}),
    )
    assert answer.proposed_value is None
    assert answer.source == "UNKNOWN"


def test_legacy_free_text_profile_does_not_guess_a_radio() -> None:
    """The old blob reads like an answer. It cannot fill Yes or No, so it does not try."""
    legacy = profile_with({"summary": "Authorized to work in the US", "sponsorshipRequired": False})
    answer = propose_answer_for_detected_field(
        field_label="Are you legally authorized to work in the United States?",
        field_type="radio",
        canonical_profile=legacy,
    )
    assert answer.proposed_value is None


def test_united_states_in_the_label_is_not_a_home_state_field() -> None:
    """The label ends in the token "state"; the address rules must not claim it.

    Before this, an unanswered profile answered "Are you legally authorized to
    work in the United States?" with the applicant's own state.
    """
    profile = {
        "profile": {
            "legalName": "Grace Hopper",
            "address": {"state": "Virginia", "country": "United States"},
            "workAuthorization": {},
        }
    }
    answer = propose_answer_for_detected_field(
        field_label="Are you legally authorized to work in the United States?",
        field_type="radio",
        canonical_profile=profile,
    )
    assert answer.proposed_value is None


def test_a_real_state_field_still_gets_the_state() -> None:
    profile = {"profile": {"legalName": "Grace Hopper", "address": {"state": "Virginia"}}}
    answer = propose_answer_for_detected_field(
        field_label="State", field_type="text", canonical_profile=profile
    )
    assert answer.proposed_value == "Virginia"
