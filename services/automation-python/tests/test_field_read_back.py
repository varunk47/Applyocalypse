"""Executable tests for the read-back that proves a typed value survived.

Typing is the right way to fill a text field: it fires the key events an
autocomplete widget listens for, which a native value assignment never does. It
is also unverified, and a React-controlled input routinely discards it. These
run the REAL script produced by ``build_verify_field_value_script`` against the
same DOM stub the write tests use, because asserting on the text of a JavaScript
string constant proves nothing about what a browser does with it.
"""
from __future__ import annotations

import pytest
from js_bridge import run_browser_script, state_for

from applyocalypse_automation.browser.adapter import BrowserField
from applyocalypse_automation.browser.field_detection import (
    build_verify_field_value_script,
    parse_apply_field_result,
)


def text_field_holding(value: str, *, field_type: str = "text") -> dict:
    return {
        "elements": [
            {
                "tag": "form",
                "children": [
                    {"tag": "label", "attrs": {"for": "answer"}, "text": "Your answer"},
                    {
                        "tag": "input",
                        "attrs": {"id": "answer", "name": "answer", "type": field_type},
                        "react": True,
                        "value": value,
                    },
                ],
            }
        ]
    }


FIELD = BrowserField(
    field_id="answer",
    label="Your answer",
    field_type="text",
    selector="#answer",
    required=True,
    confidence=1.0,
)


def verify(dom_value: str, reviewed_value: str) -> dict:
    return run_browser_script(build_verify_field_value_script("#answer", reviewed_value), text_field_holding(dom_value))


def test_a_value_that_survived_typing_reads_back_as_applied() -> None:
    outcome = verify("ada@example.com", "ada@example.com")
    result = parse_apply_field_result(outcome["result"], FIELD)

    assert result.ok is True, result.message
    assert result.payload["value_matched"] is True
    assert result.payload["verified"] is True


def test_a_value_react_discarded_reads_back_as_not_applied() -> None:
    """The keystrokes happened; the value did not stick. The run must know."""
    outcome = verify("", "Ada Byron")
    result = parse_apply_field_result(outcome["result"], FIELD)

    assert result.ok is False
    assert result.payload["value_matched"] is False


def test_a_page_that_expanded_the_typed_value_counts_as_applied() -> None:
    """The portal's own canonical form is an acceptance, not a lost write."""
    outcome = verify("New York, NY, United States", "New York")
    result = parse_apply_field_result(outcome["result"], FIELD)

    assert result.ok is True, result.message
    assert result.payload["match_mode"] == "expanded"


@pytest.mark.parametrize(
    ("dom_value", "reviewed_value"),
    [
        ("ada@example.com", "ada@example.com"),
        ("", "Ada Byron"),
        ("New York, NY, United States", "New York"),
        ("Alex Rivera", "Ada Byron"),
    ],
)
def test_reading_a_field_back_never_writes_to_it(dom_value: str, reviewed_value: str) -> None:
    """A read-back that repaired the field would hide the very bug it looks for.

    It would also clobber an autocomplete's expansion with the shorter typed
    form, undoing a selection the portal made on the applicant's behalf.
    """
    outcome = verify(dom_value, reviewed_value)
    state = state_for(outcome["state"], "answer")

    assert state["value"] == dom_value
    assert state["native_value_writes"] == 0
    assert state["focus_count"] == 0


def test_a_missing_field_is_reported_rather_than_assumed_filled() -> None:
    outcome = run_browser_script(
        build_verify_field_value_script("#nowhere", "Ada Byron"), text_field_holding("Ada Byron")
    )
    result = parse_apply_field_result(outcome["result"], FIELD)

    assert result.ok is False
    assert "not found" in result.message
