"""<input type="date"> and <input type="number"> take a wire format, not prose.

A date input accepts exactly ``yyyy-mm-dd`` through ``.value`` and silently drops
anything else; a number input drops anything it cannot parse. Both used to be
routed to the driver's keystroke path, so a reviewed "June 15, 2019" or "$120,000"
left the control empty and the write reported a failure with nothing to say about
why. They now go through the injected script, which coerces what it can and
refuses -- loudly, with the run paused for a human -- what it cannot.

The refusals are the point of the file. An ambiguous 03/04/2019 is a date the page
never says the format of, and a guess writes a plausible wrong answer that no later
check can catch.
"""
from __future__ import annotations

import pytest
from js_bridge import run_browser_script, state_for

from applyocalypse_automation.browser.field_detection import (
    SCRIPTED_WRITE_FIELD_TYPES,
    build_apply_field_value_script,
)


def _spec(input_type: str) -> dict:
    return {
        "elements": [
            {"tag": "input", "attrs": {"id": "answer", "name": "answer", "type": input_type}, "react": True}
        ]
    }


def _write(input_type: str, reviewed_value: str) -> dict:
    outcome = run_browser_script(build_apply_field_value_script("#answer", reviewed_value), _spec(input_type))
    return {"result": outcome["result"], "value": state_for(outcome["state"], "answer")["value"]}


def test_both_types_are_routed_to_the_scripted_write() -> None:
    """Without this the coercion below is dead code: the adapters would keep typing."""
    assert {"date", "number"} <= SCRIPTED_WRITE_FIELD_TYPES


@pytest.mark.parametrize(
    ("reviewed_value", "expected"),
    [
        # Already in the wire format.
        ("2019-06-15", "2019-06-15"),
        ("2019-6-5", "2019-06-05"),
        ("2019/06/15", "2019-06-15"),
        # A spelled-out month is unambiguous in either order.
        ("June 15, 2019", "2019-06-15"),
        ("15 June 2019", "2019-06-15"),
        ("Jun 15 2019", "2019-06-15"),
        ("1 September 2024", "2024-09-01"),
        # Numeric, but only one component can be the month.
        ("15/06/2019", "2019-06-15"),
        ("06/15/2019", "2019-06-15"),
        ("31.12.2020", "2020-12-31"),
    ],
)
def test_date_is_coerced_to_the_wire_format(reviewed_value, expected) -> None:
    written = _write("date", reviewed_value)

    assert written["result"]["ok"] is True, written["result"]
    assert written["value"] == expected


@pytest.mark.parametrize(
    "reviewed_value",
    [
        # Both components could be the month and the page never says which.
        "03/04/2019",
        "01/02/2020",
        # No day at all.
        "2019-06",
        "June 2019",
        # Not a date.
        "immediately",
        "ASAP",
        "",
        # A day that month does not have.
        "2019-02-29",
        "31 June 2019",
        "2019-13-01",
    ],
)
def test_an_unclear_date_refuses_rather_than_guessing(reviewed_value) -> None:
    written = _write("date", reviewed_value)

    assert written["result"]["ok"] is False, written["result"]
    assert written["result"]["value_matched"] is False
    # Nothing may be written when we refuse.
    assert written["value"] == ""


@pytest.mark.parametrize(
    ("reviewed_value", "expected"),
    [
        ("5", "5"),
        ("7.5", "7.5"),
        ("-3", "-3"),
        # Money as a person writes it.
        ("$120,000", "120000"),
        ("120,000", "120000"),
        ("£ 95000", "95000"),
        ("1,234,567", "1234567"),
        ("2,500.75", "2500.75"),
    ],
)
def test_number_is_stripped_down_to_a_number(reviewed_value, expected) -> None:
    written = _write("number", reviewed_value)

    assert written["result"]["ok"] is True, written["result"]
    assert written["value"] == expected


@pytest.mark.parametrize(
    "reviewed_value",
    [
        # A comma that is not a thousands separator: 1,5 is not 15.
        "1,5",
        "12,34",
        # Shorthand a form cannot store.
        "120k",
        "about 5",
        "5-7",
        "five",
        "",
    ],
)
def test_a_value_that_is_not_a_number_refuses(reviewed_value) -> None:
    written = _write("number", reviewed_value)

    assert written["result"]["ok"] is False, written["result"]
    assert written["value"] == ""


def test_tel_is_left_to_the_typing_path() -> None:
    """A phone field takes free text: "+1 (555) 010-9999" is a valid answer."""
    assert "tel" not in SCRIPTED_WRITE_FIELD_TYPES
