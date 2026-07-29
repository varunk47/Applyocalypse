"""CLAUDE.md safety invariant #2: EEO / criminal-history / previous-employer
answers are ALWAYS ``requires_review=True``.

These tests exist to prove that no environment variable — in particular
``APPLYO_AUTOFILL_APPROVED_DEFAULTS`` — can open a path that auto-fills one of
those three categories, and that no generic profile rule can quietly write the
applicant's own contact details into one of those fields.
"""
from __future__ import annotations

import itertools

import pytest

from applyocalypse_automation.answers import (
    SENSITIVE_REVIEW_CATEGORIES,
    propose_answer_for_detected_field,
    sensitive_review_category,
)
from applyocalypse_automation.browser.adapter import BrowserField
from applyocalypse_automation.field_resolution import proposed_answer_for_browser_field

PROFILE = {
    "profile": {
        "legalName": "Grace Hopper",
        "firstName": "Grace",
        "lastName": "Hopper",
        "email": "grace@example.com",
        "applicationEmail": "grace@apps.example.com",
        "phone": "+1-555-1234",
        "location": "Arlington, VA",
        "linkedinUrl": "https://linkedin.com/in/grace-hopper",
        "address": {
            "country": "United States",
            "city": "Arlington",
            "state": "Virginia",
            "addressLine1": "123 Main St",
            "postalCode": "22201",
            "county": "Arlington County",
        },
        "equalEmploymentDefaults": {
            "gender": "Female",
            "race": "Asian",
            "disability": "No",
            "veteran": "No",
            "hispanicOrLatino": "No",
            "sexualOrientation": ["Heterosexual"],
            "lgbtq": "No",
        },
    }
}

# Every value the applicant owns. None of these may be proposed for a field in one
# of the three always-review categories: that would be a silent cross-assignment.
OWN_PROFILE_VALUES = frozenset(
    {
        "Grace Hopper",
        "Grace",
        "Hopper",
        "grace@example.com",
        "grace@apps.example.com",
        "+1-555-1234",
        "Arlington, VA",
        "United States",
        "Arlington",
        "Virginia",
        "123 Main St",
        "22201",
        "Arlington County",
        "https://linkedin.com/in/grace-hopper",
    }
)

EEO_LABELS = (
    "Gender",
    "Gender identity",
    "What is your race?",
    "Race / ethnicity",
    "Please describe your ethnicity",
    "Veteran status",
    "Protected veteran / military service",
    "Disability status",
    "Do you have a disability?",
    "Are you Hispanic or Latino?",
    "Do you identify as LGBTQ+?",
    "Sexual Orientation",
)

CRIMINAL_HISTORY_LABELS = (
    "Have you ever been convicted of a felony?",
    "Any criminal history?",
    "Have you been convicted of a misdemeanor?",
    "Criminal record city",
    "Please list the city where the conviction occurred",
    "Conviction details: name of court",
    "Felony conviction - state",
    "Do you consent to a criminal background check?",
    "Have you ever been arrested?",
)

PREVIOUS_EMPLOYER_LABELS = (
    "Have you previously worked for us?",
    "Are you a former employee?",
    "Have you ever been employed by this company?",
    "Are you or have you been employed with CertCo?",
    "Name of previous employer",
    "Previous employer",
    "Previous employer name",
    "Previous employer city",
    "Previous employer state",
    "Most recent employer name",
    "Dates of previous employment",
    "Reason for leaving previous employer",
    "Previous supervisor name",
)

SENSITIVE_LABELS = tuple(
    itertools.chain(
        (("EEO", label) for label in EEO_LABELS),
        (("CRIMINAL_HISTORY", label) for label in CRIMINAL_HISTORY_LABELS),
        (("PREVIOUS_EMPLOYER", label) for label in PREVIOUS_EMPLOYER_LABELS),
    )
)

# Every value the env var has ever been given, plus the "not set at all" case.
AUTOFILL_ENV_VALUES = (None, "", "0", "1", "true", "TRUE", "yes")

FIELD_TYPES = ("text", "textarea", "select", "radio", "checkbox")


def _make_field(label: str, field_type: str) -> BrowserField:
    return BrowserField(
        field_id="f1",
        label=label,
        field_type=field_type,
        selector=None,
        required=True,
        confidence=0.9,
    )


@pytest.mark.parametrize(("category", "label"), SENSITIVE_LABELS)
def test_label_is_classified_into_its_always_review_category(category: str, label: str) -> None:
    assert sensitive_review_category(label) == category


@pytest.mark.parametrize(("category", "label"), SENSITIVE_LABELS)
@pytest.mark.parametrize("autofill_approved_defaults", [False, True])
def test_sensitive_categories_always_require_review_via_answers(
    category: str, label: str, autofill_approved_defaults: bool
) -> None:
    answer = propose_answer_for_detected_field(
        field_label=label,
        field_type="text",
        canonical_profile=PROFILE,
        autofill_approved_defaults=autofill_approved_defaults,
    )

    assert answer.requires_review is True, f"{category} label '{label}' must stay review-gated"
    assert answer.proposed_value not in OWN_PROFILE_VALUES, (
        f"{category} label '{label}' was cross-assigned the applicant's own value "
        f"{answer.proposed_value!r}"
    )


@pytest.mark.parametrize(("category", "label"), SENSITIVE_LABELS)
@pytest.mark.parametrize("env_value", AUTOFILL_ENV_VALUES)
@pytest.mark.parametrize("password_secret_set", [False, True])
def test_sensitive_categories_always_require_review_via_env(
    category: str,
    label: str,
    env_value: str | None,
    password_secret_set: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if env_value is None:
        monkeypatch.delenv("APPLYO_AUTOFILL_APPROVED_DEFAULTS", raising=False)
    else:
        monkeypatch.setenv("APPLYO_AUTOFILL_APPROVED_DEFAULTS", env_value)
    if password_secret_set:
        monkeypatch.setenv("APPLYO_APPLICATION_PASSWORD", "not-a-real-password")
    else:
        monkeypatch.delenv("APPLYO_APPLICATION_PASSWORD", raising=False)

    answer = proposed_answer_for_browser_field(_make_field(label, "text"), PROFILE)

    assert answer.requires_review is True, f"{category} label '{label}' must stay review-gated"
    assert answer.proposed_value not in OWN_PROFILE_VALUES


@pytest.mark.parametrize(("category", "label"), SENSITIVE_LABELS)
@pytest.mark.parametrize("field_type", FIELD_TYPES)
def test_sensitive_categories_require_review_for_every_field_type(
    category: str, label: str, field_type: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APPLYO_AUTOFILL_APPROVED_DEFAULTS", "1")

    answer = proposed_answer_for_browser_field(_make_field(label, field_type), PROFILE)

    assert answer.requires_review is True
    assert answer.proposed_value not in OWN_PROFILE_VALUES


def test_sensitive_review_categories_are_the_three_claude_md_invariant_categories() -> None:
    assert SENSITIVE_REVIEW_CATEGORIES == ("EEO", "CRIMINAL_HISTORY", "PREVIOUS_EMPLOYER")


@pytest.mark.parametrize(
    "label",
    [
        "First name",
        "Email address",
        "Address line 1",
        "Country",
    ],
)
def test_ordinary_fields_are_not_misclassified_as_sensitive(label: str) -> None:
    assert sensitive_review_category(label) is None
