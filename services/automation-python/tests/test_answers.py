"""Table-driven tests for propose_answer_for_detected_field."""
from __future__ import annotations

import pytest

from applyocalypse_automation.answers import propose_answer_for_detected_field

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
        "githubUrl": "https://github.com/grace-hopper",
        "links": [
            {"label": "LinkedIn", "url": "https://linkedin.com/in/grace-hopper-via-links"},
        ],
        "address": {
            "country": "United States",
            "city": "Arlington",
            "state": "Virginia",
            "addressLine1": "123 Main St",
            "addressLine2": "Apt 4B",
            "postalCode": "22201",
            "county": "Arlington County",
        },
        "workAuthorization": {
            "summary": "F-1 OPT, no sponsorship required",
        },
        "equalEmploymentDefaults": {
            "authorizedToWorkUS": "Yes",
            "requiresSponsorship": "Yes",
            "sponsorshipDetailText": "I'm authorized to work full-time for 36 months on F-1 OPT.",
            "disability": "No",
            "gender": "Female",
            "lgbtq": "No",
            "veteran": "No",
            "race": "Asian",
            "hispanicOrLatino": "No",
            "sexualOrientation": ["Heterosexual"],
        },
    }
}

EMPTY_PROFILE: dict = {"profile": {}}


@pytest.mark.parametrize("label,field_type,expected_value,expected_review,expected_source", [
    # ── Standard profile fields ──────────────────────────────────────────────
    ("Email address", "text", "grace@apps.example.com", False, "PROFILE"),
    ("Phone number", "tel", "+1-555-1234", False, "PROFILE"),
    ("Full legal name", "text", "Grace Hopper", False, "PROFILE"),

    # ── First / last name ────────────────────────────────────────────────────
    ("First name", "text", "Grace", None, "PROFILE"),   # review depends on autofill flag
    ("Last name", "text", "Hopper", None, "PROFILE"),

    # ── Address fields ───────────────────────────────────────────────────────
    ("Country", "text", "United States", None, "PROFILE"),
    ("City", "text", "Arlington", None, "PROFILE"),
    ("State", "text", "Virginia", None, "PROFILE"),
    ("Address line 1", "text", "123 Main St", None, "PROFILE"),
    ("Address line 2", "text", "Apt 4B", None, "PROFILE"),
    ("Zip code / Postal code", "text", "22201", None, "PROFILE"),
    ("County", "text", "Arlington County", None, "PROFILE"),

    # ── LinkedIn / GitHub (convenience fields) ───────────────────────────────
    ("LinkedIn profile URL", "url", "https://linkedin.com/in/grace-hopper", None, "PROFILE"),
    ("GitHub profile", "url", "https://github.com/grace-hopper", None, "PROFILE"),

    # ── EEO fields (always requires_review=True) ─────────────────────────────
    ("Gender identity", "select", "Female", True, "PROFILE"),
    ("Disability status", "select", "No", True, "PROFILE"),
    ("Veteran status", "radio", "No", True, "PROFILE"),
    ("Race / ethnicity", "select", "Asian", True, "PROFILE"),
    ("Are you Hispanic or Latino?", "radio", "No", True, "PROFILE"),
    ("LGBTQ+ identity", "select", "No", True, "PROFILE"),
    ("How would you describe your sexual orientation?", "select", "Heterosexual", True, "PROFILE"),
    ("Sexual Orientation", "select", "Heterosexual", True, "PROFILE"),
    ("Do you identify as LGBTQ+?", "select", "No", True, "PROFILE"),

    # ── Previously employed / criminal (always requires_review=True) ─────────
    ("Have you previously worked for us?", "radio", "No", True, "PROFILE"),
    ("Are you a former employee?", "radio", "No", True, "PROFILE"),
    ("Have you ever been convicted of a felony?", "radio", "No", True, "PROFILE"),
    ("Any criminal history?", "radio", "No", True, "PROFILE"),

    # ── Work auth free-text ──────────────────────────────────────────────────
    ("Work authorization details", "textarea", "I'm authorized to work full-time for 36 months on F-1 OPT.", True, "PROFILE"),
])
def test_propose_answer_labels(
    label: str,
    field_type: str,
    expected_value: str | None,
    expected_review: bool | None,
    expected_source: str,
) -> None:
    answer = propose_answer_for_detected_field(
        field_label=label,
        field_type=field_type,
        canonical_profile=PROFILE,
    )
    assert answer.proposed_value == expected_value, f"Label '{label}': value mismatch"
    if expected_review is not None:
        assert answer.requires_review is expected_review, f"Label '{label}': requires_review mismatch"
    assert answer.source == expected_source, f"Label '{label}': source mismatch"


def test_autofill_approved_defaults_removes_review_for_address() -> None:
    answer = propose_answer_for_detected_field(
        field_label="Country",
        field_type="text",
        canonical_profile=PROFILE,
        autofill_approved_defaults=True,
    )
    assert answer.proposed_value == "United States"
    assert answer.requires_review is False


def test_autofill_approved_defaults_removes_review_for_names() -> None:
    first = propose_answer_for_detected_field(
        field_label="First name",
        field_type="text",
        canonical_profile=PROFILE,
        autofill_approved_defaults=True,
    )
    last = propose_answer_for_detected_field(
        field_label="Last name",
        field_type="text",
        canonical_profile=PROFILE,
        autofill_approved_defaults=True,
    )
    assert first.requires_review is False
    assert last.requires_review is False


def test_autofill_approved_defaults_does_not_remove_review_for_eeo() -> None:
    answer = propose_answer_for_detected_field(
        field_label="Gender identity",
        field_type="select",
        canonical_profile=PROFILE,
        autofill_approved_defaults=True,
    )
    assert answer.requires_review is True


def test_autofill_approved_defaults_does_not_remove_review_for_criminal() -> None:
    answer = propose_answer_for_detected_field(
        field_label="Have you been convicted of a felony?",
        field_type="radio",
        canonical_profile=PROFILE,
        autofill_approved_defaults=True,
    )
    assert answer.requires_review is True


def test_linkedin_falls_back_to_links_when_no_convenience_field() -> None:
    profile_no_convenience = {
        "profile": {
            "links": [{"label": "LinkedIn", "url": "https://linkedin.com/in/ada"}],
        }
    }
    answer = propose_answer_for_detected_field(
        field_label="LinkedIn profile URL",
        field_type="url",
        canonical_profile=profile_no_convenience,
    )
    assert answer.proposed_value == "https://linkedin.com/in/ada"


def test_unknown_field_returns_unknown_source() -> None:
    answer = propose_answer_for_detected_field(
        field_label="Totally unknown field xyz",
        field_type="text",
        canonical_profile=EMPTY_PROFILE,
    )
    assert answer.source == "UNKNOWN"
    assert answer.proposed_value is None
    assert answer.requires_review is True


def test_first_name_derived_from_legal_name_when_not_set() -> None:
    profile = {"profile": {"legalName": "Ada Lovelace"}}
    answer = propose_answer_for_detected_field(
        field_label="First name",
        field_type="text",
        canonical_profile=profile,
    )
    assert answer.proposed_value == "Ada"


def test_last_name_derived_from_legal_name_when_not_set() -> None:
    profile = {"profile": {"legalName": "Ada Lovelace"}}
    answer = propose_answer_for_detected_field(
        field_label="Last name",
        field_type="text",
        canonical_profile=profile,
    )
    assert answer.proposed_value == "Lovelace"


def test_sexual_orientation_list_joined_as_comma_separated() -> None:
    profile = {
        "profile": {
            "equalEmploymentDefaults": {
                "sexualOrientation": ["Heterosexual", "Prefer not to say"],
            }
        }
    }
    answer = propose_answer_for_detected_field(
        field_label="Sexual Orientation",
        field_type="select",
        canonical_profile=profile,
    )
    assert answer.proposed_value == "Heterosexual, Prefer not to say"
    assert answer.requires_review is True
