"""Signature fields are signed with the legal name and today's date, always review-gated."""
from __future__ import annotations

from datetime import date

import pytest

from applyocalypse_automation.answers import propose_answer_for_detected_field

PROFILE = {"profile": {"legalName": "Grace Hopper", "firstName": "Grace", "lastName": "Hopper"}}
TODAY = date.today().strftime("%m/%d/%Y")


@pytest.mark.parametrize("label,field_type,expected_value", [
    ("Signature", "text", "Grace Hopper"),
    ("Electronic signature", "text", "Grace Hopper"),
    ("E-Signature", "text", "Grace Hopper"),
    ("Please type your full name as your signature", "text", "Grace Hopper"),
    ("Applicant signature (type your full legal name)", "text", "Grace Hopper"),
    ("Signature date", "text", TODAY),
    ("Date signed", "date", TODAY),
    ("Today's date", "text", TODAY),
    ("Date of signature", "text", TODAY),
])
def test_signature_fields_are_signed_and_held_for_review(label: str, field_type: str, expected_value: str) -> None:
    answer = propose_answer_for_detected_field(field_label=label, field_type=field_type, canonical_profile=PROFILE)
    assert answer.proposed_value == expected_value
    assert answer.requires_review is True
    assert answer.source == "PROFILE"


def test_signature_stays_review_gated_even_with_autofill_approved() -> None:
    answer = propose_answer_for_detected_field(
        field_label="Electronic signature", field_type="text", canonical_profile=PROFILE,
        autofill_approved_defaults=True,
    )
    assert answer.proposed_value == "Grace Hopper"
    assert answer.requires_review is True


@pytest.mark.parametrize("label,field_type", [
    # An acknowledgement box is not a place to type a name.
    ("I agree that typing my name constitutes my electronic signature", "checkbox"),
    ("Signature", "radio"),
])
def test_signature_choice_fields_never_receive_a_name(label: str, field_type: str) -> None:
    answer = propose_answer_for_detected_field(field_label=label, field_type=field_type, canonical_profile=PROFILE)
    assert answer.proposed_value != "Grace Hopper"


def test_signature_without_a_legal_name_is_left_blank() -> None:
    answer = propose_answer_for_detected_field(
        field_label="Signature", field_type="text", canonical_profile={"profile": {}},
    )
    assert answer.proposed_value is None
    assert answer.requires_review is True


@pytest.mark.parametrize("label", ["Start date", "Graduation date", "Date of birth", "Available start date"])
def test_ordinary_date_fields_are_not_signed(label: str) -> None:
    answer = propose_answer_for_detected_field(field_label=label, field_type="text", canonical_profile=PROFILE)
    assert answer.proposed_value != TODAY
