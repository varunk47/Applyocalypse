"""Radio groups are discovered as a question with answers, not N separate fields.

The write half already treats a group as one control: ``set_radio`` collects every
input sharing the ``name`` and ranks their labels. Discovery did not, and emitted
each button as its own field carrying ``options: []``, so the review layer was
asked N times which of N buttons to tick instead of once which answer the question
takes. The field shape is deliberately unchanged -- one field per button, because
that is what the selector has to aim at -- but every one of them now reports the
whole group's options, in the same shape a <select> reports.
"""
from __future__ import annotations

from js_bridge import run_browser_script

from applyocalypse_automation.browser.field_detection import (
    DOM_FIELD_DISCOVERY_SCRIPT,
    fields_from_dom_snapshot,
)


def _radio(id_: str, name: str, value: str) -> dict:
    return {"tag": "input", "attrs": {"id": id_, "name": name, "type": "radio", "value": value}}


def _discover(spec: dict) -> list:
    return fields_from_dom_snapshot(run_browser_script(DOM_FIELD_DISCOVERY_SCRIPT, spec)["result"])


def _options_of(fields: list, field_id: str) -> list[dict]:
    field = next(f for f in fields if f.metadata.get("id") == field_id)
    return field.metadata["options"]


def test_each_button_reports_the_whole_group() -> None:
    spec = {
        "elements": [
            {
                "tag": "form",
                "children": [
                    {"tag": "label", "attrs": {"for": "wfh-yes"}, "text": "Yes"},
                    _radio("wfh-yes", "remote", "yes"),
                    {"tag": "label", "attrs": {"for": "wfh-no"}, "text": "No"},
                    _radio("wfh-no", "remote", "no"),
                ],
            }
        ]
    }

    fields = _discover(spec)

    assert len(fields) == 2
    expected = [
        {"value": "yes", "label": "Yes", "selected": False, "disabled": False},
        {"value": "no", "label": "No", "selected": False, "disabled": False},
    ]
    # Both buttons answer the same question, so both carry the same answers.
    assert _options_of(fields, "wfh-yes") == expected
    assert _options_of(fields, "wfh-no") == expected


def test_a_shared_legend_never_becomes_every_option_label() -> None:
    """Unlabelled peers resolve to the group's legend, which names none of them."""
    spec = {
        "elements": [
            {
                "tag": "fieldset",
                "children": [
                    {"tag": "legend", "text": "Do you require sponsorship?"},
                    _radio("sp-yes", "sponsorship", "Yes"),
                    _radio("sp-no", "sponsorship", "No"),
                ],
            }
        ]
    }

    options = _options_of(_discover(spec), "sp-yes")

    assert [option["label"] for option in options] == ["Yes", "No"]


def test_a_checked_button_is_reported_as_the_selected_option() -> None:
    spec = {
        "elements": [
            {
                "tag": "form",
                "children": [
                    {"tag": "label", "attrs": {"for": "v-yes"}, "text": "Yes"},
                    {
                        "tag": "input",
                        "attrs": {"id": "v-yes", "name": "veteran", "type": "radio", "value": "yes"},
                        "checked": True,
                    },
                    {"tag": "label", "attrs": {"for": "v-no"}, "text": "No"},
                    _radio("v-no", "veteran", "no"),
                ],
            }
        ]
    }

    options = _options_of(_discover(spec), "v-no")

    assert [option["selected"] for option in options] == [True, False]


def test_groups_do_not_leak_into_each_other() -> None:
    spec = {
        "elements": [
            {
                "tag": "form",
                "children": [
                    {"tag": "label", "attrs": {"for": "a-yes"}, "text": "Yes"},
                    _radio("a-yes", "relocate", "yes"),
                    {"tag": "label", "attrs": {"for": "b-now"}, "text": "Immediately"},
                    _radio("b-now", "start_date", "now"),
                    {"tag": "label", "attrs": {"for": "b-later"}, "text": "In two weeks"},
                    _radio("b-later", "start_date", "later"),
                ],
            }
        ]
    }

    fields = _discover(spec)

    assert [option["value"] for option in _options_of(fields, "a-yes")] == ["yes"]
    assert [option["value"] for option in _options_of(fields, "b-now")] == ["now", "later"]


def test_non_radio_controls_still_report_no_options() -> None:
    spec = {
        "elements": [
            {
                "tag": "form",
                "children": [
                    {"tag": "label", "attrs": {"for": "consent"}, "text": "I agree"},
                    {"tag": "input", "attrs": {"id": "consent", "name": "consent", "type": "checkbox"}},
                    {"tag": "label", "attrs": {"for": "name"}, "text": "Full name"},
                    {"tag": "input", "attrs": {"id": "name", "name": "name", "type": "text"}},
                ],
            }
        ]
    }

    fields = _discover(spec)

    assert _options_of(fields, "consent") == []
    assert _options_of(fields, "name") == []
