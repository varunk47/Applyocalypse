"""ARIA widget pickers must be discovered, not silently skipped (audit finding F9).

Workday, Ashby and most React portals never emit a ``<select>``. Their questions are
divs and inputs carrying ``role=combobox|listbox|radiogroup``, which the native
``input, textarea, select`` sweep cannot see at all. An invisible question is worse
than an unfillable one: the run would reach the submit gate believing a required
field was answered.
"""

from __future__ import annotations

import pytest

from applyocalypse_automation.browser.html_replay import analyze_portal_html_fixture

_URL = "https://example.test/apply"


def _page(body: str) -> str:
    return f"<html><head><title>Apply</title></head><body><form>{body}</form></body></html>"


def _field_by_label(html: str, label: str):
    analysis = analyze_portal_html_fixture(_URL, html)
    matches = [candidate for candidate in analysis.fields if candidate.label == label]
    assert matches, f"{label!r} was never discovered; got {[f.label for f in analysis.fields]}"
    return matches[0]


@pytest.mark.parametrize(
    ("role", "option_role", "expected_type"),
    [
        ("listbox", "option", "aria_listbox"),
        ("radiogroup", "radio", "aria_radiogroup"),
    ],
)
def test_rendered_widget_exposes_its_options(role: str, option_role: str, expected_type: str) -> None:
    field = _field_by_label(
        _page(
            f'<div role="{role}" id="auth" aria-label="Work authorization" aria-required="true">'
            f'<div role="{option_role}" data-value="yes">Yes</div>'
            f'<div role="{option_role}" data-value="no">No</div>'
            "</div>"
        ),
        "Work authorization",
    )

    assert field.field_type == expected_type
    assert field.selector == "#auth"
    assert field.required is True
    assert field.metadata["options_rendered"] is True
    assert [option["label"] for option in field.metadata["options"]] == ["Yes", "No"]
    assert [option["value"] for option in field.metadata["options"]] == ["yes", "no"]


def test_closed_combobox_is_surfaced_with_no_options() -> None:
    """A combobox that was never opened owns no options yet.

    Recording that honestly is what lets the write path pause for a human instead of
    guessing at a value the portal never offered.
    """
    field = _field_by_label(
        _page('<div role="combobox" id="country" aria-label="Country" aria-expanded="false"></div>'),
        "Country",
    )

    assert field.field_type == "aria_combobox"
    assert field.metadata["options_rendered"] is False
    assert field.metadata["options"] == []
    assert field.metadata["aria_expanded"] == "false"


def test_input_wearing_a_combobox_role_is_not_a_text_field() -> None:
    """The false-success case.

    ``<input role="combobox">`` has a ``value`` property, so the generic text path
    would write into it and then read that same text back as proof it worked, while
    the widget's real state stayed empty. It must be claimed by the ARIA sweep.
    """
    field = _field_by_label(
        _page('<input role="combobox" id="school" aria-label="School" aria-haspopup="listbox" />'),
        "School",
    )

    assert field.field_type == "aria_combobox"
    assert field.metadata["tag_name"] == "input"


def test_workday_style_picker_without_a_role_is_discovered() -> None:
    """Workday wires pickers to a popup listbox instead of declaring a role."""
    field = _field_by_label(
        _page(
            '<button data-automation-id="countryDropdown" aria-haspopup="listbox" '
            'aria-label="Country of residence"></button>'
        ),
        "Country of residence",
    )

    assert field.field_type == "aria_combobox"
    assert field.selector == '[data-automation-id="countryDropdown"]'
    assert field.metadata["automation_id"] == "countryDropdown"


def test_wrapper_elements_do_not_end_the_widget_early() -> None:
    """Options are closed off the frame lifecycle, not by tag name.

    A plain ``<div>`` wrapper inside a listbox shares the widget's tag, so closing by
    tag name would end the widget at the wrapper and drop every option after it.
    """
    field = _field_by_label(
        _page(
            '<div role="listbox" id="dept" aria-label="Department">'
            '<div class="group-heading">Engineering</div>'
            '<div role="option" data-value="be">Backend</div>'
            '<div role="option" data-value="fe">Frontend</div>'
            "</div>"
        ),
        "Department",
    )

    assert [option["label"] for option in field.metadata["options"]] == ["Backend", "Frontend"]


def test_native_select_is_untouched_by_the_aria_sweep() -> None:
    """The native path must keep behaving exactly as it did."""
    field = _field_by_label(
        _page('<select id="src" aria-label="How did you hear about us"><option>Referral</option></select>'),
        "How did you hear about us",
    )

    assert field.field_type == "select"
