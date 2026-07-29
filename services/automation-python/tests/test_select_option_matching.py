"""Table-driven tests for ranked <select> option matching (audit finding F9).

The old matcher accepted a substring match in *either* direction and took the
first hit, so "India" selected "Indiana" and a reviewed knockout answer such as
"No, I do not require sponsorship" could land on whichever "No"-adjacent option
happened to come first. The replacement ranks candidates (exact > token prefix >
token run) and refuses to guess: a tie or a miss must return ok:false.
"""
from __future__ import annotations

import pytest
from js_bridge import run_browser_script, state_for

from applyocalypse_automation.browser.field_detection import build_apply_field_value_script


def _select_spec(options: list[dict[str, str]]) -> dict:
    return {
        "elements": [
            {
                "tag": "select",
                "attrs": {"id": "answer", "name": "answer"},
                "react": True,
                "options": options,
            }
        ]
    }


def _labels(*labels: str) -> list[dict[str, str]]:
    return [{"label": label, "value": label} for label in labels]


@pytest.mark.parametrize(
    ("options", "reviewed_value", "expected_label", "expected_tier"),
    [
        # Exact wins over every looser tier, in either DOM order.
        (_labels("Indiana", "India"), "India", "India", "exact"),
        (_labels("India", "Indiana"), "India", "India", "exact"),
        # A bare "No" must win over the long sponsorship wording.
        (_labels("Yes", "No", "No, I do not require sponsorship"), "No", "No", "exact"),
        # And a long reviewed answer must collapse onto the only sane option.
        (_labels("Yes", "No"), "No, I do not require sponsorship", "No", "prefix"),
        (_labels("Yes", "No"), "Yes, I am legally authorized to work", "Yes", "prefix"),
        # Match on the option value, not only the label.
        ([{"label": "United States", "value": "US"}, {"label": "India", "value": "IN"}], "US", "United States", "exact"),
        # Token-run match anywhere in the option label.
        (_labels("Prefer not to say", "Woman", "Man"), "Prefer not to say", "Prefer not to say", "exact"),
        (
            _labels("A Master of Science degree", "A Bachelor of Arts degree"),
            "Master of Science",
            "A Master of Science degree",
            "token",
        ),
    ],
)
def test_ranked_option_match_selects_the_unique_winner(options, reviewed_value, expected_label, expected_tier) -> None:
    outcome = run_browser_script(build_apply_field_value_script("#answer", reviewed_value), _select_spec(options))
    result = outcome["result"]

    assert result["ok"] is True, result
    assert result["selected_label"] == expected_label
    assert result["match_tier"] == expected_tier
    assert state_for(outcome["state"], "answer")["selected_labels"] == [expected_label]


@pytest.mark.parametrize(
    ("options", "reviewed_value", "expected_ambiguous"),
    [
        # "India" must never fall through to "Indiana" when India is absent.
        (_labels("Indiana", "Indonesia"), "India", False),
        # Genuinely ambiguous: two options are equally good prefix matches.
        (_labels("Yes, I am authorized", "Yes, with sponsorship"), "Yes", True),
        (_labels("Master of Science", "Master of Arts"), "Master", True),
        # No relationship at all.
        (_labels("Male", "Female"), "Decline to self identify", False),
        # A single character fragment must not match anything.
        (_labels("Yes", "No"), "o", False),
    ],
)
def test_ambiguous_or_missing_option_never_guesses(options, reviewed_value, expected_ambiguous) -> None:
    outcome = run_browser_script(build_apply_field_value_script("#answer", reviewed_value), _select_spec(options))
    result = outcome["result"]

    assert result["ok"] is False, result
    assert result["action"] == "select_option"
    assert result["value_matched"] is False
    if expected_ambiguous:
        assert result["ambiguity_code"] == "AMBIGUOUS_SELECT_OPTION"
        assert len(result["candidate_labels"]) >= 2
    else:
        assert "ambiguity_code" not in result
    # Nothing may be selected when we refuse to choose.
    assert state_for(outcome["state"], "answer")["selected_labels"] == []


def test_disabled_placeholder_options_are_never_selected() -> None:
    spec = _select_spec(
        [
            {"label": "Select an option", "value": "", "disabled": True, "selected": True},
            {"label": "Yes", "value": "yes"},
            {"label": "No", "value": "no"},
        ]
    )

    outcome = run_browser_script(build_apply_field_value_script("#answer", "No"), spec)

    assert outcome["result"]["ok"] is True
    assert state_for(outcome["state"], "answer")["selected_labels"] == ["No"]
