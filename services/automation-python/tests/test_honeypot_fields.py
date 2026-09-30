"""Honeypot inputs are dropped at detection, before anything can propose a value.

Workday's create-account page carries a text input labelled "Enter website. This
input is for robots only, do not enter if you're human." The website rule answered
it with the profile's LinkedIn URL, and with approved defaults on it would have been
filled without review, which is exactly the signal the trap exists to catch.
"""
from __future__ import annotations

import pytest

from applyocalypse_automation.browser.field_detection import fields_from_dom_snapshot, is_honeypot_label


def _raw(label: str, *, selector: str = "#x", field_type: str = "text") -> dict[str, object]:
    return {"label": label, "label_source": "aria_label", "selector": selector, "field_type": field_type}


@pytest.mark.parametrize(
    "label",
    [
        "Enter website. This input is for robots only, do not enter if you're human.",
        "Enter website. This input is for robots only, do not enter if you’re human.",
        "If you are human, leave this field blank",
        "Leave this field empty",
        "Do not fill this field",
        "honeypot",
    ],
)
def test_a_trap_for_bots_is_recognised_by_its_label(label: str) -> None:
    assert is_honeypot_label(label) is True


@pytest.mark.parametrize(
    "label",
    [
        "Website",
        "Personal website or portfolio",
        "Email Address*",
        "Leave blank if you have no middle name",
        "Are you human resources certified?",
    ],
)
def test_a_real_question_is_not_mistaken_for_one(label: str) -> None:
    assert is_honeypot_label(label) is False


def test_the_workday_create_account_page_keeps_only_its_real_fields() -> None:
    fields = fields_from_dom_snapshot(
        [
            _raw("Email Address*", selector="#email"),
            _raw("Password*", selector="#password", field_type="password"),
            _raw("Verify New Password*", selector="#verify", field_type="password"),
            _raw("Enter website. This input is for robots only, do not enter if you're human.", selector="#website"),
        ]
    )

    assert [field.label for field in fields] == ["Email Address*", "Password*", "Verify New Password*"]
