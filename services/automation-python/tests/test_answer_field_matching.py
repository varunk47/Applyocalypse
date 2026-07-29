"""Table-driven tests for ranked approved-answer to detected-field matching.

The old matcher accepted a bidirectional substring hit (``a in b or b in a``),
which silently cross-assigns values: the approved "Phone" answer landed in
"Phone country code", "Email" landed in "Email me about similar jobs", and the
work-authorization answer landed in the relocation question. The replacement
ranks candidates and refuses to apply anything unless there is a unique winner.
"""
from __future__ import annotations

import pytest

from applyocalypse_automation.browser.adapter import BrowserField
from applyocalypse_automation.field_resolution import (
    approved_value_for_field,
    match_approved_answer,
)


def _field(label: str, field_type: str = "text") -> BrowserField:
    return BrowserField(
        field_id="f1",
        label=label,
        field_type=field_type,
        selector=None,
        required=True,
        confidence=0.9,
    )


def _answers(*rows: tuple[str, str, str]) -> list[dict[str, str]]:
    return [{"fieldLabel": label, "fieldType": field_type, "value": value} for label, field_type, value in rows]


EMAIL_ANSWER = ("Email", "email", "grace@example.com")
PHONE_ANSWER = ("Phone", "tel", "+1-555-1234")
CITY_ANSWER = ("City", "text", "Arlington")
NAME_ANSWER = ("Legal name", "text", "Grace Hopper")
WORK_AUTH_ANSWER = ("Are you authorized to work", "text", "Yes")


@pytest.mark.parametrize(
    ("field_label", "field_type", "answers", "expected_value", "expected_strategy"),
    [
        # ── Exact, modulo case and punctuation ────────────────────────────────
        ("Email", "email", [EMAIL_ANSWER], "grace@example.com", "exact"),
        ("email:", "email", [EMAIL_ANSWER], "grace@example.com", "exact"),
        ("E-Mail *", "email", [("e mail", "email", "grace@example.com")], "grace@example.com", "exact"),
        # ── Same tokens, different order ──────────────────────────────────────
        ("Name (legal)", "text", [NAME_ANSWER], "Grace Hopper", "token_set"),
        # ── One side adds only non-discriminating filler ──────────────────────
        ("Email address", "email", [EMAIL_ANSWER], "grace@example.com", "subset"),
        ("Phone number", "tel", [PHONE_ANSWER], "+1-555-1234", "subset"),
        ("Phone No.", "tel", [PHONE_ANSWER], "+1-555-1234", "subset"),
        # ── Long question, same contiguous stem ───────────────────────────────
        (
            "Are you authorized to work in the US?",
            "radio",
            [WORK_AUTH_ANSWER],
            "Yes",
            "phrase",
        ),
        # ── Higher tier wins over a lower-tier competitor ─────────────────────
        (
            "Phone",
            "tel",
            [PHONE_ANSWER, ("Phone number", "tel", "+1-555-9999")],
            "+1-555-1234",
            "exact",
        ),
        # ── Duplicate label carrying the same value is not ambiguous ──────────
        ("Email", "email", [EMAIL_ANSWER, EMAIL_ANSWER], "grace@example.com", "exact"),
        # ── Type-only fallback when no label candidate clears the floor ───────
        ("Contact", "email", [EMAIL_ANSWER], "grace@example.com", "type_fallback"),
    ],
)
def test_ranked_match_returns_the_unique_winner(
    field_label: str,
    field_type: str,
    answers: list[tuple[str, str, str]],
    expected_value: str,
    expected_strategy: str,
) -> None:
    result = match_approved_answer(_field(field_label, field_type), _answers(*answers))

    assert result.outcome == "MATCHED", f"'{field_label}': expected a match, got {result.outcome}"
    assert result.match is not None
    assert result.match.value == expected_value
    assert result.match.strategy == expected_strategy
    assert approved_value_for_field(_field(field_label, field_type), _answers(*answers)) == expected_value


@pytest.mark.parametrize(
    ("field_label", "field_type", "answers"),
    [
        # ── Cross-assignment traps from the portal-filling audit ──────────────
        ("Phone country code", "text", [PHONE_ANSWER]),
        ("Phone type", "select", [PHONE_ANSWER]),
        ("Email me about similar jobs", "checkbox", [EMAIL_ANSWER]),
        ("City of birth", "text", [CITY_ANSWER]),
        ("Name of referrer", "text", [NAME_ANSWER]),
        ("Preferred name", "text", [NAME_ANSWER]),
        ("First name", "text", [NAME_ANSWER]),
        ("Are you willing to relocate?", "radio", [WORK_AUTH_ANSWER]),
        ("Do you require sponsorship?", "radio", [WORK_AUTH_ANSWER]),
        # ── Nothing to match against ──────────────────────────────────────────
        ("Email", "email", []),
        ("Totally unrelated question", "text", [EMAIL_ANSWER, PHONE_ANSWER, CITY_ANSWER]),
        # ── Unusable rows are skipped, not guessed at ─────────────────────────
        ("Email", "email", [("", "email", "grace@example.com")]),
        ("Email", "email", [("Email", "email", "   ")]),
    ],
)
def test_no_match_never_guesses(
    field_label: str, field_type: str, answers: list[tuple[str, str, str]]
) -> None:
    result = match_approved_answer(_field(field_label, field_type), _answers(*answers))

    assert result.outcome == "NO_MATCH", f"'{field_label}': expected NO_MATCH, got {result.outcome}"
    assert result.match is None
    assert approved_value_for_field(_field(field_label, field_type), _answers(*answers)) is None


@pytest.mark.parametrize(
    ("field_label", "field_type", "answers", "expected_competitors"),
    [
        # Two approved answers claim the same field at the same tier.
        (
            "Phone",
            "tel",
            [("Phone", "tel", "+1-555-1234"), ("phone", "tel", "+1-555-9999")],
            ("Phone", "phone"),
        ),
        (
            "Email address",
            "email",
            [("Email", "email", "grace@example.com"), ("Email address", "email", "g@work.example.com")],
            ("Email address",),
        ),
        # Type-only fallback with several distinct values of that type.
        (
            "Contact",
            "email",
            [("Email", "email", "grace@example.com"), ("Alternate", "email", "g@work.example.com")],
            ("Email", "Alternate"),
        ),
    ],
)
def test_ambiguous_matches_are_reported_and_never_applied(
    field_label: str,
    field_type: str,
    answers: list[tuple[str, str, str]],
    expected_competitors: tuple[str, ...],
) -> None:
    result = match_approved_answer(_field(field_label, field_type), _answers(*answers))

    if len(expected_competitors) == 1:
        # A strictly higher tier resolves the contest instead of blocking on it.
        assert result.outcome == "MATCHED"
        assert result.match is not None
        assert result.match.answer_label == expected_competitors[0]
        return

    assert result.outcome == "AMBIGUOUS", f"'{field_label}': expected AMBIGUOUS, got {result.outcome}"
    assert result.match is None
    assert set(result.competing_labels) == set(expected_competitors)
    # An ambiguous contest must be indistinguishable from "do not fill" to callers
    # that only look at the value, but distinguishable via the outcome.
    assert approved_value_for_field(_field(field_label, field_type), _answers(*answers)) is None


@pytest.mark.parametrize("approved_answers", [None, {}, "Email", 7, [None, 3, "x"]])
def test_malformed_approved_answers_yield_no_match(approved_answers: object) -> None:
    result = match_approved_answer(_field("Email", "email"), approved_answers)

    assert result.outcome == "NO_MATCH"
    assert result.match is None
