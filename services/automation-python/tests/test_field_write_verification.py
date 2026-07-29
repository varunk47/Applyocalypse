"""Executable tests for the React-safe field write and its read-back verification.

These run the REAL script produced by ``build_apply_field_value_script`` against a
DOM stub that reproduces React's ``inputValueTracking``: React installs an own
``value``/``checked`` descriptor on the node whose setter refreshes React's cached
copy. A plain ``node.value = x`` therefore leaves React believing nothing changed
and the synthetic change event is discarded. Only a write through the *prototype*
descriptor setter is observed by the framework.
"""
from __future__ import annotations

import json

import pytest
from js_bridge import run_browser_script, state_for

from applyocalypse_automation.browser.adapter import BrowserField
from applyocalypse_automation.browser.field_detection import (
    build_apply_field_value_script,
    parse_apply_field_result,
)

REACT_TEXT_FIELD = {
    "elements": [
        {
            "tag": "form",
            "children": [
                {"tag": "label", "attrs": {"for": "email"}, "text": "Email address"},
                {"tag": "input", "attrs": {"id": "email", "name": "email", "type": "email"}, "react": True},
            ],
        }
    ]
}

REACT_SELECT_FIELD = {
    "elements": [
        {
            "tag": "form",
            "children": [
                {"tag": "label", "attrs": {"for": "sponsor"}, "text": "Do you require sponsorship?"},
                {
                    "tag": "select",
                    "attrs": {"id": "sponsor", "name": "sponsor"},
                    "react": True,
                    "options": [
                        {"label": "Please select", "value": ""},
                        {"label": "Yes", "value": "yes"},
                        {"label": "No", "value": "no"},
                    ],
                },
            ],
        }
    ]
}

REACT_CONSENT_CHECKBOX = {
    "elements": [
        {
            "tag": "form",
            "children": [
                {
                    "tag": "label",
                    "attrs": {"for": "consent"},
                    "text": "I agree to the terms",
                },
                {
                    "tag": "input",
                    "attrs": {"id": "consent", "name": "consent", "type": "checkbox", "value": "yes"},
                    "react": True,
                },
            ],
        }
    ]
}

REACT_RADIO_GROUP = {
    "elements": [
        {
            "tag": "form",
            "children": [
                {
                    "tag": "label",
                    "children": [
                        {
                            "tag": "input",
                            "attrs": {"id": "remote", "name": "location", "type": "radio", "value": "remote"},
                            "react": True,
                        }
                    ],
                    "text": "Remote",
                },
                {
                    "tag": "label",
                    "children": [
                        {
                            "tag": "input",
                            "attrs": {"id": "onsite", "name": "location", "type": "radio", "value": "onsite"},
                            "react": True,
                        }
                    ],
                    "text": "Onsite",
                },
            ],
        }
    ]
}


@pytest.mark.parametrize(
    ("spec", "selector", "value", "element_id"),
    [
        (REACT_TEXT_FIELD, "#email", "grace@example.com", "email"),
        (REACT_SELECT_FIELD, "#sponsor", "No", "sponsor"),
        (REACT_CONSENT_CHECKBOX, "#consent", "Yes", "consent"),
        (REACT_RADIO_GROUP, 'input[name="location"][value="remote"]', "Remote", "remote"),
    ],
)
def test_writes_register_with_a_react_controlled_field(spec, selector, value, element_id) -> None:
    outcome = run_browser_script(build_apply_field_value_script(selector, value), spec)
    result = outcome["result"]
    element = state_for(outcome["state"], element_id)

    assert result["ok"] is True, result
    assert element["react_tracked"] is True
    # The decisive assertion: React's value tracker must observe the change.
    assert element["react_saw_change"] is True, result
    assert element["focus_count"] >= 1
    assert element["blur_count"] >= 1


def test_select_write_sets_option_selected_not_only_value() -> None:
    outcome = run_browser_script(build_apply_field_value_script("#sponsor", "No"), REACT_SELECT_FIELD)

    assert outcome["result"]["ok"] is True
    assert state_for(outcome["state"], "sponsor")["selected_labels"] == ["No"]


def test_checkbox_write_uses_the_native_checked_setter() -> None:
    outcome = run_browser_script(build_apply_field_value_script("#consent", "Yes"), REACT_CONSENT_CHECKBOX)
    element = state_for(outcome["state"], "consent")

    assert outcome["result"]["ok"] is True
    assert element["checked"] is True
    assert element["native_checked_writes"] >= 1


@pytest.mark.parametrize(
    ("spec", "selector", "value", "expected_actual"),
    [
        (
            {
                "elements": [
                    {
                        "tag": "input",
                        "attrs": {"id": "email", "name": "email", "type": "email"},
                        "react": True,
                        "revertOnChange": "",
                    }
                ]
            },
            "#email",
            "grace@example.com",
            "",
        ),
        (
            {
                "elements": [
                    {
                        "tag": "input",
                        "attrs": {"id": "phone", "name": "phone", "type": "tel"},
                        "revertOnChange": "555",
                    }
                ]
            },
            "#phone",
            "+1-555-0100",
            "555",
        ),
    ],
)
def test_a_write_that_does_not_stick_reports_not_ok_with_expected_and_actual(
    spec, selector, value, expected_actual
) -> None:
    result = run_browser_script(build_apply_field_value_script(selector, value), spec)["result"]

    assert result["ok"] is False
    assert result["verified"] is True
    assert result["value_matched"] is False
    assert result["match_mode"] == "mismatch"
    assert result["expected"] == value
    assert result["actual"] == expected_actual


def test_checkbox_that_refuses_the_write_reports_not_ok() -> None:
    spec = {
        "elements": [
            {
                "tag": "input",
                "attrs": {"id": "consent", "name": "consent", "type": "checkbox"},
                "react": True,
                "revertCheckedOnChange": False,
            }
        ]
    }

    result = run_browser_script(build_apply_field_value_script("#consent", "Yes"), spec)["result"]

    assert result["ok"] is False
    assert result["value_matched"] is False
    assert result["expected"] == "true"
    assert result["actual"] == "false"


def test_reformatted_text_value_is_accepted_as_verified() -> None:
    spec = {
        "elements": [
            {
                "tag": "input",
                "attrs": {"id": "phone", "name": "phone", "type": "tel"},
                "revertOnChange": "(555) 010-0000",
            }
        ]
    }

    result = run_browser_script(build_apply_field_value_script("#phone", "5550100000"), spec)["result"]

    assert result["ok"] is True
    assert result["match_mode"] == "reformatted"


def test_missing_field_reports_a_structured_failure() -> None:
    result = run_browser_script(build_apply_field_value_script("#nope", "value"), {"elements": []})["result"]

    assert result["ok"] is False
    assert result["action"] == "query"
    assert result["verified"] is False


def _field(label: str, field_type: str = "text", **metadata: str) -> BrowserField:
    return BrowserField(
        field_id="field:0:text:x",
        label=label,
        field_type=field_type,
        selector="#x",
        required=False,
        confidence=0.78,
        metadata=dict(metadata),
    )


SECRET_CODE = "884213"

# runner.py spreads this payload straight into emitted events (including the OTP
# failure event), so a verified read-back must never carry the value itself.
REDACTION_CASES: tuple[tuple[str, BrowserField, bool], ...] = (
    ("password input type", _field("Account access", field_type="password"), True),
    ("label mentions a code", _field("Enter the code we sent"), True),
    ("label mentions a one-time passcode", _field("One-time passcode"), True),
    ("autocomplete marks a one-time code", _field("Verify", autocomplete="one-time-code"), True),
    ("name mentions otp", _field("Verify", name="otpValue"), True),
    ("label mentions ssn", _field("SSN"), True),
    ("plain email field is not secret", _field("Email address", name="email"), False),
    ("innocent substring does not trip redaction", _field("Encoded portfolio link", name="portfolio"), False),
)


@pytest.mark.parametrize(
    ("description", "field", "expect_redacted"),
    [pytest.param(*case, id=case[0]) for case in REDACTION_CASES],
)
def test_verification_values_are_redacted_for_secret_bearing_fields(description, field, expect_redacted) -> None:
    raw = json.dumps(
        {
            "ok": False,
            "action": "set_value",
            "field_type": field.field_type,
            "verified": True,
            "value_matched": False,
            "match_mode": "mismatch",
            "expected": SECRET_CODE,
            "actual": SECRET_CODE[:3],
            "expected_length": len(SECRET_CODE),
            "actual_length": 3,
        }
    )

    payload = parse_apply_field_result(raw, field).payload

    if expect_redacted:
        assert payload["values_redacted"] is True
        assert SECRET_CODE not in json.dumps(payload)
        for key in ("expected", "actual", "expected_length", "actual_length"):
            assert key not in payload
    else:
        assert "values_redacted" not in payload
        assert payload["expected"] == SECRET_CODE
        assert payload["actual"] == SECRET_CODE[:3]
    # The non-value verification signal survives redaction either way.
    assert payload["verified"] is True
    assert payload["value_matched"] is False
    assert payload["match_mode"] == "mismatch"
