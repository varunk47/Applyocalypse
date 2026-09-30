"""References, reason for leaving and the legal yes/no answers come from the profile.

Reason for leaving and the history questions stay review-gated (CLAUDE.md
safety invariant #2); references are the user's own list and fill directly.
"""

from __future__ import annotations

from typing import Any

import pytest

from applyocalypse_automation.answers import propose_answer_for_detected_field

PROFILE: dict[str, Any] = {
    "profile": {
        "legalName": "Grace Hopper",
        "email": "grace@example.com",
        "phone": "+1-555-1234",
        "references": [
            {"name": "Ada Lovelace", "relationship": "Former manager", "company": "Analytical Engines",
             "title": "Director", "email": "ada@example.com", "phone": "+1-555-0001"},
            {"name": "Alan Turing", "relationship": "Colleague", "company": "Bletchley",
             "title": None, "email": "alan@example.com", "phone": "+1-555-0002"},
        ],
        "equalEmploymentDefaults": {"criminalRecordDefault": "Yes", "previouslyEmployedDefault": "No"},
    },
    "experience": [
        {"company": "Navy", "title": "Rear Admiral", "startDate": "1967", "endDate": "1986",
         "reasonForLeaving": "Retired"},
        {"company": "Remington Rand", "title": "Engineer", "startDate": "1949", "endDate": "1967",
         "reasonForLeaving": "Returned to the Navy"},
    ],
}


def _answer(label: str, field_type: str = "text", profile: dict[str, Any] = PROFILE):
    return propose_answer_for_detected_field(field_label=label, field_type=field_type, canonical_profile=profile)


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Reference Name", "Ada Lovelace"),
        ("Reference 1 Email", "ada@example.com"),
        ("Reference 2 Phone Number", "+1-555-0002"),
        ("Second reference: name", "Alan Turing"),
        ("Reference relationship", "Former manager"),
        ("Reference 2 Company", "Bletchley"),
        ("Reference Title", "Director"),
        # a third reference the user never gave is left empty, not borrowed
        ("Reference 3 Name", None),
    ],
)
def test_a_reference_field_takes_the_matching_reference(label: str, expected: str | None) -> None:
    answer = _answer(label)
    assert answer.proposed_value == expected
    assert answer.requires_review is (expected is None)


@pytest.mark.parametrize("label", ["Job reference number", "Requisition reference", "How did you hear about us? (referral)"])
def test_other_uses_of_the_word_are_not_references(label: str) -> None:
    assert _answer(label).proposed_value not in {"Ada Lovelace", "ada@example.com", "+1-555-0001"}


def test_reason_for_leaving_comes_from_the_most_recent_job_and_is_held_for_review() -> None:
    answer = _answer("Reason for leaving")
    assert answer.proposed_value == "Retired"
    assert answer.requires_review is True


def test_reason_for_leaving_is_empty_when_the_user_gave_none() -> None:
    profile = {**PROFILE, "experience": [{"company": "Navy", "title": "Admiral"}]}
    answer = _answer("Reason for leaving", profile=profile)
    assert answer.proposed_value is None
    assert answer.requires_review is True


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        (PROFILE, "Yes"),
        # no stored answer keeps the old default
        ({"profile": {}}, "No"),
    ],
)
def test_the_criminal_history_question_uses_the_profile_answer(profile: dict[str, Any], expected: str) -> None:
    answer = _answer("Have you ever been convicted of a felony?", "radio", profile)
    assert answer.proposed_value == expected
    assert answer.requires_review is True
