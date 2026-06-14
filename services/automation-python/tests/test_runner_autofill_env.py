"""Tests for the APPLYO_AUTOFILL_APPROVED_DEFAULTS env var wiring in runner.py.

Verifies that proposed_answer_for_browser_field passes autofill_approved_defaults
from the environment to propose_answer_for_detected_field, and that EEO fields
remain requires_review=True regardless of the flag.
"""
from __future__ import annotations

import pytest

from applyocalypse_automation.browser.adapter import BrowserField
from applyocalypse_automation.runner import proposed_answer_for_browser_field

PROFILE = {
    "profile": {
        "legalName": "Grace Hopper",
        "firstName": "Grace",
        "lastName": "Hopper",
        "email": "grace@example.com",
        "applicationEmail": "grace@apps.example.com",
        "phone": "+1-555-1234",
        "location": "Arlington, VA",
        "address": {
            "country": "United States",
            "city": "Arlington",
            "state": "Virginia",
            "addressLine1": "123 Main St",
            "addressLine2": "Apt 4B",
            "postalCode": "22201",
        },
        "equalEmploymentDefaults": {
            "gender": "Female",
            "disability": "No",
            "veteran": "No",
        },
    }
}


def _make_field(label: str, field_type: str) -> BrowserField:
    return BrowserField(
        field_id="test-field",
        label=label,
        field_type=field_type,
        selector=None,
        required=False,
        confidence=0.9,
    )


def test_address_field_requires_review_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the env var, address fields require review (default behaviour)."""
    monkeypatch.delenv("APPLYO_AUTOFILL_APPROVED_DEFAULTS", raising=False)
    field = _make_field("Address line 1", "text")
    answer = proposed_answer_for_browser_field(field, PROFILE)
    assert answer.proposed_value == "123 Main St"
    assert answer.requires_review is True


def test_address_field_no_review_with_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """With APPLYO_AUTOFILL_APPROVED_DEFAULTS=1, address fields skip review."""
    monkeypatch.setenv("APPLYO_AUTOFILL_APPROVED_DEFAULTS", "1")
    field = _make_field("Address line 1", "text")
    answer = proposed_answer_for_browser_field(field, PROFILE)
    assert answer.proposed_value == "123 Main St"
    assert answer.requires_review is False


def test_eeo_field_always_requires_review_with_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """EEO fields must remain requires_review=True even when the flag is on."""
    monkeypatch.setenv("APPLYO_AUTOFILL_APPROVED_DEFAULTS", "1")
    field = _make_field("Gender identity", "select")
    answer = proposed_answer_for_browser_field(field, PROFILE)
    assert answer.proposed_value == "Female"
    assert answer.requires_review is True


def test_eeo_field_requires_review_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """EEO fields must remain requires_review=True without the flag too."""
    monkeypatch.delenv("APPLYO_AUTOFILL_APPROVED_DEFAULTS", raising=False)
    field = _make_field("Veteran status", "radio")
    answer = proposed_answer_for_browser_field(field, PROFILE)
    assert answer.proposed_value == "No"
    assert answer.requires_review is True
