"""Preference rules: the user's own answers, chosen per job at fill time.

A rule says "for this question, answer this", optionally only when the job's
location, company or portal matches. The rule with the most conditions that all
hold wins. Two equally specific rules that disagree answer nothing and ask the
user, because picking one would be a guess.
"""
from __future__ import annotations

import pytest

from applyocalypse_automation.answers import propose_answer_for_detected_field
from applyocalypse_automation.browser.adapter import BrowserField
from applyocalypse_automation.field_resolution import proposed_answer_for_browser_field
from applyocalypse_automation.preference_rules import resolve_preference_rule, with_job_context


def _rule(question: str, answer: str, **conditions: str) -> dict[str, object]:
    return {"question": question, "answer": answer, "conditions": conditions}


ADDRESS_RULES = [
    _rule("address line 1", "1 Default St"),
    _rule("address line 1", "10 Peachtree St", location="GA"),
    _rule("address line 1", "20 Main St", location="TX"),
    _rule("address line 1", "30 Bank Plaza", location="GA", company="Bank of America"),
]


@pytest.mark.parametrize(
    ("job_context", "expected"),
    [
        ({"location": "Atlanta, GA"}, "10 Peachtree St"),
        ({"location": "Dallas, TX"}, "20 Main St"),
        ({"location": "Seattle, WA"}, "1 Default St"),
        ({}, "1 Default St"),
        ({"location": "Atlanta, GA", "company": "Bank of America"}, "30 Bank Plaza"),
        # Whole words only: "GA" must not match inside "Chicago".
        ({"location": "Chicago, IL"}, "1 Default St"),
    ],
)
def test_the_most_specific_rule_whose_conditions_hold_wins(job_context: dict[str, str], expected: str) -> None:
    outcome = resolve_preference_rule("Address Line 1*", ADDRESS_RULES, job_context)

    assert outcome.answer == expected
    assert outcome.ambiguous is False


def test_a_question_no_rule_covers_is_left_to_the_other_answer_sources() -> None:
    outcome = resolve_preference_rule("Phone Number", ADDRESS_RULES, {"location": "Atlanta, GA"})

    assert outcome.answer is None
    assert outcome.ambiguous is False


def test_two_equally_specific_rules_that_disagree_answer_nothing() -> None:
    rules = [_rule("start date", "2 weeks", location="GA"), _rule("start date", "Immediately", company="Acme")]

    outcome = resolve_preference_rule("Earliest start date", rules, {"location": "Atlanta, GA", "company": "Acme"})

    assert outcome.answer is None
    assert outcome.ambiguous is True


def test_equally_specific_rules_that_agree_are_not_a_conflict() -> None:
    rules = [_rule("start date", "2 weeks", location="GA"), _rule("start date", "2 weeks", company="Acme")]

    outcome = resolve_preference_rule("Earliest start date", rules, {"location": "Atlanta, GA", "company": "Acme"})

    assert outcome.answer == "2 weeks"


def test_a_disabled_or_malformed_rule_is_ignored() -> None:
    rules = [
        {**_rule("salary", "150000"), "enabled": False},
        {"question": "salary"},
        "not a rule",
        _rule("salary", "120000"),
    ]

    assert resolve_preference_rule("Desired salary", rules, {}).answer == "120000"


def test_a_condition_on_an_unknown_key_never_holds() -> None:
    """A rule the resolver cannot evaluate must not apply everywhere by accident."""
    rules = [_rule("salary", "150000", seniority="senior")]

    assert resolve_preference_rule("Desired salary", rules, {"location": "Atlanta, GA"}).answer is None


PROFILE = {
    "profile": {"firstName": "Grace", "lastName": "Hopper", "address": {"addressLine1": "123 Main St"}},
    "preferenceRules": ADDRESS_RULES,
    "jobContext": {"location": "Atlanta, GA"},
}


def test_a_rule_answers_ahead_of_the_profile_at_fill_time() -> None:
    answer = propose_answer_for_detected_field(
        field_label="Address Line 1", field_type="text", canonical_profile=PROFILE, autofill_approved_defaults=True
    )

    assert answer.proposed_value == "10 Peachtree St"
    assert answer.source == "PROFILE"
    assert answer.requires_review is False


def test_a_rule_answer_is_reviewed_unless_approved_defaults_are_on() -> None:
    answer = propose_answer_for_detected_field(
        field_label="Address Line 1", field_type="text", canonical_profile=PROFILE, autofill_approved_defaults=False
    )

    assert answer.proposed_value == "10 Peachtree St"
    assert answer.requires_review is True


def test_a_conflict_asks_the_user_instead_of_falling_back_to_the_profile() -> None:
    profile = {
        **PROFILE,
        "preferenceRules": [_rule("address line 1", "A", location="GA"), _rule("address line 1", "B", location="Atlanta")],
    }

    answer = propose_answer_for_detected_field(
        field_label="Address Line 1", field_type="text", canonical_profile=profile, autofill_approved_defaults=True
    )

    assert answer.proposed_value is None
    assert answer.requires_review is True


@pytest.mark.parametrize(
    "label",
    [
        "Have you ever been convicted of a felony?",
        "Have you previously been employed by Bank of America?",
        "What is your gender?",
    ],
)
def test_a_rule_never_lifts_the_review_gate_on_a_sensitive_question(label: str) -> None:
    profile = {**PROFILE, "preferenceRules": [_rule(label, "No")]}

    answer = propose_answer_for_detected_field(
        field_label=label, field_type="text", canonical_profile=profile, autofill_approved_defaults=True
    )

    assert answer.proposed_value == "No"
    assert answer.requires_review is True


def test_the_job_target_becomes_the_context_rules_are_judged_against() -> None:
    profile = {"profile": {"firstName": "Grace"}}
    job_metadata = {"id": "j1", "company": "Bank of America", "role": "Data Scientist I", "location": "Atlanta, GA", "portal": ""}

    enriched = with_job_context(profile, job_metadata)

    assert enriched["jobContext"] == {"company": "Bank of America", "location": "Atlanta, GA"}
    assert "jobContext" not in profile


@pytest.mark.parametrize(
    ("label", "field_type"),
    [("Password", "password"), ("Create password", "text"), ("Verification code", "text"), ("Enter OTP", "text")],
)
def test_a_rule_never_answers_a_secret_field(label: str, field_type: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """A rule's answer is stored as a proposal, and a password or code must never be stored in plaintext."""
    monkeypatch.delenv("APPLYO_APPLICATION_PASSWORD", raising=False)
    profile = {**PROFILE, "preferenceRules": [_rule(label, "hunter2")]}
    field = BrowserField(field_id="f", label=label, field_type=field_type, selector="#f", required=True, confidence=0.9)

    answer = proposed_answer_for_browser_field(field, profile)

    assert answer.proposed_value != "hunter2"
