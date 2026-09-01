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


def _make_field(
    label: str, field_type: str, *, field_name: str | None = None
) -> BrowserField:
    return BrowserField(
        field_id="f1",
        label=label,
        field_type=field_type,
        selector=None,
        required=True,
        confidence=0.9,
        metadata={"name": field_name} if field_name else {},
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


# Measured, not imagined. Sampling 38 live Greenhouse postings across 20 boards
# on 2026-09-01 turned up 40 distinct questions the ATS itself files under
# `compliance` (EEOC) or `demographic_questions`. These eight are the ones the
# label matcher used to miss: questions invariant #2 says must always be
# review-gated, which used to fall through to the generic profile rules. A
# `field_name` of None is a question the API publishes with no machine name.
LIVE_EEO_QUESTIONS_THAT_USED_TO_SLIP = (
    ("Are you a person of transgender experience?", None),
    ("DisabilityStatus", "disability_status"),
    ("Do you identify as a member of the LGBT2QIA+ community?", None),
    ("Do you identify as transgender?", None),
    ("I identify as transgender:", None),
    ("Please select up to 2 ethnicities that you most closely identify with.", None),
    ("VeteranStatus", "veteran_status"),
    ("What is your military status?", None),
)


@pytest.mark.parametrize(("label", "field_name"), LIVE_EEO_QUESTIONS_THAT_USED_TO_SLIP)
def test_live_eeo_questions_reach_the_review_gate(label: str, field_name: str | None) -> None:
    assert sensitive_review_category(label, field_name=field_name) == "EEO"


@pytest.mark.parametrize(("label", "field_name"), LIVE_EEO_QUESTIONS_THAT_USED_TO_SLIP)
def test_live_eeo_questions_require_review_end_to_end(
    label: str, field_name: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The invariant is about the proposed answer, not about the classifier."""
    monkeypatch.setenv("APPLYO_AUTOFILL_APPROVED_DEFAULTS", "1")

    answer = proposed_answer_for_browser_field(
        _make_field(label, "select", field_name=field_name), PROFILE
    )

    assert answer.requires_review is True
    assert answer.proposed_value not in OWN_PROFILE_VALUES


@pytest.mark.parametrize(
    ("label", "field_name"),
    [
        ("Voluntary Self-Identification", "disability_status"),
        ("Question 3 of 4", "veteran_status"),
        ("", "disability_status"),
    ],
)
def test_the_machine_name_gates_a_label_the_phrase_list_has_never_seen(
    label: str, field_name: str
) -> None:
    """The structural signal is the ATS's own name for the input.

    A recruiter can reword the prose freely; Greenhouse still calls the input
    ``disability_status``. Reading the name is what makes the gate structural
    rather than a bet on how somebody phrased the question.
    """
    assert sensitive_review_category(label, field_name=field_name) == "EEO"


@pytest.mark.parametrize("acronym", ["LGBTQ+", "LGBTQIA", "LGBT2QIA+", "LGBTQIA2S+"])
def test_the_same_acronym_spelled_four_ways_gates_every_time(acronym: str) -> None:
    assert sensitive_review_category(f"Do you identify as {acronym}?") == "EEO"


def test_camel_splitting_did_not_break_the_single_token_linkedin_rule() -> None:
    """The camel split lives in the gate, deliberately, not in ``label_tokens``.

    Splitting globally would turn "LinkedIn" into ("linked", "in") and the rule
    that fills the applicant's LinkedIn URL would stop matching.
    """
    answer = propose_answer_for_detected_field(
        field_label="LinkedIn Profile",
        field_type="text",
        canonical_profile=PROFILE,
    )

    assert answer.proposed_value == "https://linkedin.com/in/grace-hopper"
    assert sensitive_review_category("LinkedIn Profile") is None


@pytest.mark.parametrize(
    ("label", "field_name"),
    [
        ("First name", "first_name"),
        ("Email", "email"),
        ("City", "candidate_city"),
        ("LinkedIn Profile", "linkedin_url"),
    ],
)
def test_an_ordinary_field_with_a_benign_machine_name_stays_unclassified(
    label: str, field_name: str
) -> None:
    """The extra views are one-directional: they only ever pull a question in."""
    assert sensitive_review_category(label, field_name=field_name) is None
